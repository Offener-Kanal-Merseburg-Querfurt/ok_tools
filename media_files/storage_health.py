"""Read-speed health checks for storage locations.

``is_active`` says whether we *want* to use a location; it says nothing about
whether the box behind it still answers. ``os.path.isfile`` and ``stat`` do not
either: a degrading CIFS share keeps answering metadata instantly while
``read()`` crawls at a few KB/s or blocks outright in uninterruptible sleep.

So we measure the thing that actually matters — how fast a real file reads —
and cache the result on the location. Callers on a hot path (the export source
picker) read the cached value instead of measuring; the hourly auto-scan keeps
it current, which also means a storage degrading quietly shows up on its own
instead of only during an incident.

The read itself happens in a child process. A watchdog thread cannot interrupt
a ``read()`` stuck on CIFS — only killing the process holding it works — so
every timeout in this module is enforced by ``terminate()``/``kill()``.
"""

from django.utils import timezone
import ctypes
import logging
import multiprocessing
import os
import time


logger = logging.getLogger('django')

MB = 1024 * 1024

# How much to read and how long to wait when probing a location.
PROBE_SAMPLE_BYTES = 4 * MB
PROBE_TIMEOUT = 30.0
# Below this a storage is treated as unusable as a read source. The incident
# this guards against read at 0.03 MB/s; a healthy share does 100+.
DEFAULT_MIN_READ_MBPS = 1.0
# A measurement older than this tells us nothing about the storage right now.
DEFAULT_MAX_HEALTH_AGE_SECONDS = 2 * 3600
# Grace period between terminate() and kill() for a child stuck in I/O.
TERMINATE_GRACE = 10.0


def mp_context():
    """Return a multiprocessing context, preferring ``fork``.

    ``fork`` keeps the child cheap and needs no picklable module state;
    ``spawn`` is only a fallback for platforms without it. Children started
    through this context never touch Django, so either works.
    """
    methods = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context('fork' if 'fork' in methods else 'spawn')


def kill_child(proc):
    """Terminate a child, escalating to SIGKILL when it will not go."""
    proc.terminate()
    proc.join(TERMINATE_GRACE)
    if proc.is_alive():
        proc.kill()
        proc.join(TERMINATE_GRACE)


def _read_sample(path, sample_bytes):
    """Read up to ``sample_bytes`` from ``path``; return (bytes, seconds)."""
    read = 0
    start = time.monotonic()
    with open(path, 'rb') as handle:
        while read < sample_bytes:
            chunk = handle.read(min(MB, sample_bytes - read))
            if not chunk:
                break
            read += len(chunk)
    return read, max(time.monotonic() - start, 1e-6)


def _probe_worker(path, sample_bytes, result):
    """Child entry point: publish (bytes, seconds) into shared memory."""
    try:
        read, elapsed = _read_sample(path, sample_bytes)
        result[0] = float(read)
        result[1] = elapsed
    except BaseException:  # noqa: BLE001 - any failure means "cannot read"
        result[0] = -1.0
    # _exit, not sys.exit: skip atexit handlers inherited from the Celery
    # worker (DB connections, metrics flushes) that this child must not run.
    os._exit(0)


def probe_read_speed(path, sample_bytes=PROBE_SAMPLE_BYTES, timeout=PROBE_TIMEOUT):
    """Measure read speed of ``path`` in MB/s, or ``None`` when unreadable.

    ``None`` covers both "the file is not there" and "the storage stopped
    answering": the caller only wants to know whether reading this copy is
    worth attempting.
    """
    context = mp_context()
    result = context.Array(ctypes.c_double, 2)
    try:
        proc = context.Process(target=_probe_worker, args=(path, sample_bytes, result))
        proc.start()
    except Exception:
        logger.warning(
            'Cannot fork a probe process; reading %s in-process without a timeout',
            path, exc_info=True)
        try:
            read, elapsed = _read_sample(path, sample_bytes)
        except OSError:
            return None
        return (read / MB) / elapsed if read > 0 else None

    proc.join(timeout)
    if proc.is_alive():
        kill_child(proc)
        logger.warning('Read probe timed out after %.0fs: %s', timeout, path)
        return None

    read, elapsed = result[0], result[1]
    if read <= 0:
        return None
    return (read / MB) / elapsed


def record_read_speed(storage_location, read_mbps):
    """Store a measurement on the location without touching anything else."""
    from media_files.models import StorageLocation

    storage_location.last_read_mbps = read_mbps
    storage_location.last_health_check = timezone.now()
    StorageLocation.objects.filter(pk=storage_location.pk).update(
        last_read_mbps=read_mbps,
        last_health_check=storage_location.last_health_check,
    )


def _pick_sample_file(storage_location):
    """Return the path of a file on this location that is cheap to sample."""
    from media_files.models import VideoFile

    video = (
        VideoFile.objects
        .filter(storage_location=storage_location, is_available=True)
        .order_by('-last_scanned', '-created_at')
        .first()
    )
    return video.full_path if video else None


def measure_storage_health(storage_location, timeout=PROBE_TIMEOUT):
    """Measure and store the read speed of one location. Returns MB/s or None.

    ``None`` means the location delivered no bytes within the timeout — it is
    either empty, gone, or hung.
    """
    sample_path = _pick_sample_file(storage_location)
    if not sample_path:
        # Nothing to read: record the attempt, but do not claim a speed.
        record_read_speed(storage_location, None)
        logger.debug('No sample file on storage %s; health unknown', storage_location)
        return None

    read_mbps = probe_read_speed(sample_path, timeout=timeout)
    record_read_speed(storage_location, read_mbps)
    if read_mbps is None:
        logger.warning(
            'Storage %s did not answer a read probe (%s)',
            storage_location, sample_path)
    else:
        logger.info('Storage %s read probe: %.2f MB/s', storage_location, read_mbps)
    return read_mbps


def refresh_all_storage_health(timeout=PROBE_TIMEOUT):
    """Measure every active location. Returns ``{storage_id: mbps or None}``."""
    from media_files.models import StorageLocation

    results = {}
    for storage_location in StorageLocation.objects.filter(is_active=True):
        try:
            results[storage_location.pk] = measure_storage_health(
                storage_location, timeout=timeout)
        except Exception:
            logger.exception('Health check failed for storage %s', storage_location)
            results[storage_location.pk] = None
    return results


def health_state(
    storage_location,
    min_mbps=DEFAULT_MIN_READ_MBPS,
    max_age_seconds=DEFAULT_MAX_HEALTH_AGE_SECONDS,
):
    """Return ``True`` (fast), ``False`` (too slow / silent) or ``None`` (unknown).

    ``None`` is deliberately distinct from ``False``: a location that has never
    been measured should rank below a known-good one but above one we know is
    broken.
    """
    checked_at = storage_location.last_health_check
    if not checked_at:
        return None
    if (timezone.now() - checked_at).total_seconds() > max_age_seconds:
        return None
    if storage_location.last_read_mbps is None:
        return False
    return storage_location.last_read_mbps >= min_mbps
