"""Chunked, watchdog-supervised file copying for exports to a network share.

``shutil.copy2`` hands the whole copy to the kernel (``_fastcopy_sendfile`` on
Linux), so a CIFS server that stops answering parks the calling thread in
uninterruptible sleep: no timeout, no progress, no chance to check a cancel
flag and nothing written to the log. A Celery worker that enters that state is
lost until the mount recovers, its slot gone from a finite ``--concurrency``,
and the ``SIGKILL`` that eventually lands skips the cleanup handler — leaving
the half-written ``.tmp_`` file on the share forever.

Everything here exists to keep that from happening:

* the copy runs chunk by chunk, so bytes can be counted and reported;
* it runs in a **child process** whose byte counter the parent watches — a
  watchdog thread cannot interrupt a ``read()`` stuck on CIFS, but the parent
  can kill the process holding it and fail the task with a real reason;
* leftover ``.tmp_`` files from earlier kills are swept away.

The pre-flight "is this storage alive at all" read lives in
:mod:`media_files.storage_health`, next to the cached health it feeds.
"""

from media_files.storage_health import MB
from media_files.storage_health import kill_child
from media_files.storage_health import mp_context
from typing import Callable
from typing import Optional
import ctypes
import logging
import os
import shutil
import time


logger = logging.getLogger('django')

# 8 MB: small enough for useful watchdog granularity, large enough not to cost
# throughput on a healthy 130+ MB/s playout link.
DEFAULT_CHUNK_SIZE = 8 * MB
# No byte written for this long -> the storage is gone, not merely slow.
DEFAULT_STALL_TIMEOUT = 300.0
# How often the parent looks at the child's byte counter (and reports progress).
DEFAULT_POLL_INTERVAL = 1.0
# Room for the child's error message in shared memory.
_ERROR_BUFFER_SIZE = 512


class CopyError(Exception):
    """Base class for copy failures raised by this module."""


class CopyStalledError(CopyError):
    """The copy made no progress for longer than the stall timeout."""


def _copy_worker(src: str, dst: str, chunk_size: int, written, error) -> None:
    """Child entry point: copy chunk by chunk, publishing bytes written."""
    try:
        with open(src, 'rb') as source, open(dst, 'wb') as target:
            while True:
                chunk = source.read(chunk_size)
                if not chunk:
                    break
                target.write(chunk)
                written.value += len(chunk)
            target.flush()
            os.fsync(target.fileno())
        # copy2 preserved mtime; a plain read/write loop does not.
        shutil.copystat(src, dst)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent verbatim
        error.value = f'{type(exc).__name__}: {exc}'.encode(
            'utf-8', 'replace')[:_ERROR_BUFFER_SIZE - 1]
        os._exit(1)
    # _exit, not sys.exit: skip atexit handlers inherited from the Celery
    # worker (DB connections, metrics flushes) that this child must not run.
    os._exit(0)


def copy_with_progress(
    src: str,
    dst: str,
    progress_callback: Optional[Callable] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    stall_timeout: float = DEFAULT_STALL_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    """Copy ``src`` to ``dst`` with progress reporting and a stall watchdog.

    ``progress_callback(chunk_num, total_chunks, percent, speed_mbps)`` is
    called from the parent about once per ``poll_interval`` while bytes keep
    arriving — the same signature ``NextcloudExchangeService.upload_file_direct``
    uses, so the Celery ``update_state`` receiver needs no changes.

    Returns the number of bytes copied. Raises :class:`CopyStalledError` when
    the copy makes no progress for ``stall_timeout`` seconds, or
    :class:`CopyError` when the child fails or copies short.
    """
    total_bytes = os.path.getsize(src)
    total_chunks = max(1, -(-total_bytes // chunk_size))

    context = mp_context()
    written = context.Value(ctypes.c_longlong, 0)
    error = context.Array(ctypes.c_char, _ERROR_BUFFER_SIZE)
    try:
        proc = context.Process(
            target=_copy_worker, args=(src, dst, chunk_size, written, error))
        proc.start()
    except Exception:
        logger.warning(
            'Cannot fork a copy process; copying %s in-process without a watchdog',
            src, exc_info=True)
        return _copy_inline(src, dst, progress_callback, chunk_size,
                            total_bytes, total_chunks)

    started = time.monotonic()
    last_bytes = 0
    last_change = started
    try:
        while True:
            proc.join(poll_interval)
            current = written.value
            now = time.monotonic()

            if current != last_bytes:
                last_bytes = current
                last_change = now
                _report(progress_callback, current, total_bytes,
                        total_chunks, chunk_size, now - started)
            elif proc.is_alive() and now - last_change > stall_timeout:
                kill_child(proc)
                raise CopyStalledError(
                    f'No progress for {stall_timeout:.0f}s after '
                    f'{current / MB:.1f} MB of {total_bytes / MB:.1f} MB: {src}'
                )

            if not proc.is_alive():
                break
    finally:
        if proc.is_alive():
            kill_child(proc)

    if proc.exitcode != 0:
        reason = error.value.decode('utf-8', 'replace') or (
            f'copy process exited with {proc.exitcode}')
        raise CopyError(f'{reason} ({src} -> {dst})')

    copied = written.value
    if copied != total_bytes:
        raise CopyError(
            f'Short copy: {copied} of {total_bytes} bytes ({src} -> {dst})')
    _report(progress_callback, copied, total_bytes, total_chunks, chunk_size,
            time.monotonic() - started)
    return copied


def _report(progress_callback, current, total_bytes, total_chunks, chunk_size,
            elapsed) -> None:
    """Translate a byte count into the chunk/percent/speed the UI expects."""
    if not progress_callback:
        return
    percent = (current / total_bytes * 100.0) if total_bytes else 100.0
    speed_mbps = (current / MB / elapsed) if elapsed > 0 else 0.0
    chunk_num = min(total_chunks, max(1, -(-current // chunk_size)))
    try:
        progress_callback(chunk_num, total_chunks, percent, speed_mbps)
    except Exception:
        logger.exception('Copy progress callback failed')


def _copy_inline(src, dst, progress_callback, chunk_size, total_bytes,
                 total_chunks) -> int:
    """Chunked copy in this process. Progress, but no enforceable watchdog."""
    copied = 0
    started = time.monotonic()
    with open(src, 'rb') as source, open(dst, 'wb') as target:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            target.write(chunk)
            copied += len(chunk)
            _report(progress_callback, copied, total_bytes, total_chunks,
                    chunk_size, time.monotonic() - started)
        target.flush()
        os.fsync(target.fileno())
    shutil.copystat(src, dst)
    return copied


def sweep_stale_tmp_files(
    directory: str,
    prefix: str = '.tmp_',
    older_than_seconds: float = 24 * 3600,
) -> int:
    """Delete ``prefix*`` files in ``directory`` older than the given age.

    A copy killed by the watchdog (or by SIGKILL) never reaches its cleanup
    handler, so without this every stalled export leaves its partial file
    behind — gigabytes at a time on a share that is already near full.
    """
    if not directory or not os.path.isdir(directory):
        return 0

    cutoff = time.time() - older_than_seconds
    removed = 0
    try:
        entries = os.listdir(directory)
    except OSError:
        logger.exception('Cannot list export directory for cleanup: %s', directory)
        return 0

    for name in entries:
        if not name.startswith(prefix):
            continue
        path = os.path.join(directory, name)
        try:
            if not os.path.isfile(path) or os.path.getmtime(path) > cutoff:
                continue
            size = os.path.getsize(path)
            os.unlink(path)
            removed += 1
            logger.info('Removed stale export temp file %s (%.1f MB)', path, size / MB)
        except OSError:
            logger.warning('Could not remove stale temp file %s', path, exc_info=True)
    return removed
