"""Per-item locks that stop the same license being exported twice at once.

Pressing "Start upload" a second time used to queue a second task with the
same arguments. Both workers then went after the same source file on the same
share and wrote two different ``.tmp_`` files into the same directory: not just
duplicated work, but two readers competing for bandwidth that was already the
bottleneck, and a real chance of a half-written file being listed in
``files.txt``.

The lock is a plain ``cache.add`` on the Redis the project already runs as the
Celery broker and result backend.

TTL is the awkward part: 12 GB takes ~2 minutes on a healthy link and hours on
a sick one, so any fixed timeout either expires mid-copy or blocks the license
for a day after a crash. Instead the lock takes a short TTL that a heartbeat
thread keeps renewing while the task runs, and locks whose owning task is no
longer alive are swept by :func:`release_orphaned_locks`, called from the
existing periodic ``ok_tools.tasks.cleanup_stale_task_results_task``.
"""

from django.core.cache import cache
import logging
import threading


logger = logging.getLogger('django')

KEY_PREFIX = 'austausch:export'
KEY_PATTERN = f'{KEY_PREFIX}:*'
# Short enough that a lock left by a hard kill expires on its own before the
# next working day, long enough that a stalled copy keeps its lock while the
# watchdog runs its course.
DEFAULT_TTL = 900
# Comfortably inside the TTL, so a missed beat does not drop the lock.
DEFAULT_HEARTBEAT_INTERVAL = 180


def lock_key(mode: str, item_id) -> str:
    """Return the cache key locking one item of one export mode."""
    return f'{KEY_PREFIX}:{mode}:{item_id}'


def acquire(mode: str, item_id, task_id: str, ttl: int = DEFAULT_TTL):
    """Try to lock one item. Returns ``None`` on success, else the holder's id."""
    key = lock_key(mode, item_id)
    if cache.add(key, str(task_id), ttl):
        return None
    # The holder may have expired between add() and get(); retry once so a
    # just-freed lock is not reported as busy.
    holder = cache.get(key)
    if holder is None and cache.add(key, str(task_id), ttl):
        return None
    return holder or 'unknown'


def release(mode: str, item_id, task_id: str) -> bool:
    """Release a lock, but only when this task still holds it."""
    key = lock_key(mode, item_id)
    if cache.get(key) != str(task_id):
        return False
    cache.delete(key)
    return True


def refresh(keys, ttl: int = DEFAULT_TTL) -> None:
    """Push the expiry of the given lock keys back out to the full TTL."""
    for key in keys:
        try:
            cache.touch(key, ttl)
        except Exception:
            logger.warning('Could not refresh export lock %s', key, exc_info=True)


class ExportItemLocks:
    """Context manager locking a batch of items for the duration of a task.

    Usage::

        with ExportItemLocks(mode, ids, task_id) as locks:
            service.run(locks.acquired_ids, mode)

    ``busy`` lists the items someone else is already exporting, as
    ``{'id': …, 'task_id': …}``. They are deliberately not treated as failures:
    the caller reports them as their own category so the user sees "already
    being exported by …" instead of a misleading error.
    """

    def __init__(self, mode, item_ids, task_id, ttl=DEFAULT_TTL,
                 heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL, enabled=True):
        self.mode = mode
        self.item_ids = list(item_ids)
        self.task_id = str(task_id) if task_id else ''
        self.ttl = ttl
        self.heartbeat_interval = heartbeat_interval
        self.enabled = enabled and bool(self.task_id)
        self.acquired_ids = []
        self.busy = []
        self._stop = threading.Event()
        self._heartbeat = None

    def __enter__(self):
        if not self.enabled:
            self.acquired_ids = list(self.item_ids)
            return self

        for item_id in self.item_ids:
            try:
                holder = acquire(self.mode, item_id, self.task_id, self.ttl)
            except Exception:
                # A broken cache must not block exporting altogether; losing
                # the guard is better than losing the feature.
                logger.exception(
                    'Export lock unavailable for %s %s; proceeding unlocked',
                    self.mode, item_id)
                holder = None
            if holder is None:
                self.acquired_ids.append(item_id)
            else:
                self.busy.append({'id': item_id, 'task_id': holder})
                logger.warning(
                    'Skipping %s %s: already being exported by task %s',
                    self.mode, item_id, holder)

        if self.acquired_ids:
            self._start_heartbeat()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._heartbeat:
            self._heartbeat.join(timeout=5)
        if not self.enabled:
            return False
        for item_id in self.acquired_ids:
            try:
                release(self.mode, item_id, self.task_id)
            except Exception:
                logger.warning('Could not release export lock for %s %s',
                               self.mode, item_id, exc_info=True)
        return False

    def _start_heartbeat(self):
        keys = [lock_key(self.mode, item_id) for item_id in self.acquired_ids]

        def beat():
            while not self._stop.wait(self.heartbeat_interval):
                refresh(keys, self.ttl)

        self._heartbeat = threading.Thread(
            target=beat, name='austausch-export-lock-heartbeat', daemon=True)
        self._heartbeat.start()


def iter_locks():
    """Return ``{key: task_id}`` for all export locks, or ``{}`` if unlistable.

    Key enumeration needs a Redis-backed cache (``django_redis``); on any other
    backend there is nothing to sweep and ``{}`` is the honest answer.
    """
    if not hasattr(cache, 'keys'):
        return {}
    try:
        keys = cache.keys(KEY_PATTERN)
    except Exception:
        logger.warning('Cannot list export locks', exc_info=True)
        return {}
    return {key: cache.get(key) for key in keys}


def locked_item_ids(mode: str):
    """Return ``{item_id: task_id}`` for items currently locked in this mode.

    Used by the confirm screen to grey out items an export is already
    uploading — cheaper than losing a race on the backend, and the user can
    see why the item is unavailable.
    """
    prefix = f'{KEY_PREFIX}:{mode}:'
    locked = {}
    for key, holder in iter_locks().items():
        if key.startswith(prefix):
            locked[key[len(prefix):]] = holder
    return locked


def release_orphaned_locks(live_task_ids) -> int:
    """Drop locks whose owning Celery task is no longer running.

    ``live_task_ids`` of ``None`` means no worker answered the inspect ping —
    releasing everything on that basis would be worse than leaving the locks
    in place, so nothing is touched.
    """
    if live_task_ids is None:
        return 0

    released = 0
    for key, holder in iter_locks().items():
        if holder and str(holder) in live_task_ids:
            continue
        cache.delete(key)
        released += 1
        logger.warning('Released orphaned export lock %s (task %s)', key, holder)
    return released
