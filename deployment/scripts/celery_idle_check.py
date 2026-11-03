"""Celery idle check used by update.sh before containers are restarted.

update.sh pipes this file into a running container of the *current* release
(`docker compose exec -T web python - <mode> ...`), so it must only rely on
code that has existed for a long time: the `ok_tools.celery` app and kombu.
It is deliberately not a management command - the old image would not have it.

Settings may print to stdout while loading, so every line meant for
update.sh carries an `OKTOOLS_` prefix and everything else is ignored.

Modes:
  status <expected_workers> [paused_queue,...]
      OKTOOLS_LINE  <human readable line>   (zero or more)
      OKTOOLS_STATUS idle=<0|1> workers=<n> active=<n> reserved=<n> queued=<n>
  pause <queue,...>
      Stops the listed queues from being consumed (running tasks continue).
      OKTOOLS_PAUSED <json {queue: [worker, ...]}>
  resume <json {queue: [worker, ...]}>
      Re-adds the consumers removed by `pause` on the same workers.
      OKTOOLS_RESUMED <n>
"""

import json
import os
import sys
import time


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ok_tools.settings')

DEFAULT_QUEUES = ['copy', 'download', 'render', 'anchor_render', 'celery']
INSPECT_TIMEOUT = 5.0
ARGS_MAX_CHARS = 160


def emit(kind, text):
    print(f'OKTOOLS_{kind} {text}', flush=True)


def get_app():
    from ok_tools.celery import app
    return app


def queue_length(channel, queue):
    """Return the number of messages waiting in ``queue`` (0 if unknown)."""
    size = getattr(channel, '_size', None)
    if size is not None:
        # Redis transport: sums all priority sub-queues.
        return int(size(queue))
    try:
        return int(channel.queue_declare(queue=queue, passive=True).message_count)
    except Exception:
        # Passive declare fails when the queue does not exist yet, i.e. it is
        # empty.
        return 0


def describe_task(worker, task, now):
    name = task.get('name') or task.get('type') or '?'
    args = task.get('args')
    args_text = args if isinstance(args, str) else json.dumps(args, default=str)
    if len(args_text) > ARGS_MAX_CHARS:
        args_text = args_text[:ARGS_MAX_CHARS] + '...'
    started = task.get('time_start')
    if isinstance(started, (int, float)) and 0 < started <= now + 60:
        runtime = f'{int(now - started) // 60}m{int(now - started) % 60:02d}s'
    else:
        runtime = 'unknown'
    task_id = (task.get('id') or '')[:8]
    return f'{name}{args_text} running {runtime} on {worker} (id {task_id})'


def status(expected_workers, paused_queues):
    app = get_app()
    # With a limit the broadcast returns as soon as every expected worker
    # replied instead of always waiting for the full timeout.
    inspector = app.control.inspect(timeout=INSPECT_TIMEOUT,
                                    limit=expected_workers or None)
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    now = time.time()

    replied = set(active) | set(reserved)
    active_count = 0
    for worker in sorted(active):
        for task in active[worker] or []:
            active_count += 1
            emit('LINE', 'active: ' + describe_task(worker, task, now))
    reserved_count = sum(len(tasks or []) for tasks in reserved.values())
    if reserved_count:
        emit('LINE', f'reserved (prefetched, not started yet): {reserved_count}')

    queued_blocking = 0
    with app.connection_for_read() as conn:
        channel = conn.default_channel
        for queue in DEFAULT_QUEUES:
            length = queue_length(channel, queue)
            if not length:
                continue
            if queue in paused_queues:
                emit('LINE', f'queue {queue}: {length} waiting (paused, will run after the update)')
            else:
                queued_blocking += length
                emit('LINE', f'queue {queue}: {length} waiting')

    if len(replied) < expected_workers:
        emit('LINE', f'only {len(replied)} of {expected_workers} workers replied to inspect')

    idle = (
        active_count == 0
        and reserved_count == 0
        and queued_blocking == 0
        and len(replied) >= expected_workers
    )
    emit('STATUS', f'idle={int(idle)} workers={len(replied)} active={active_count} '
                   f'reserved={reserved_count} queued={queued_blocking}')


def pause(queues):
    app = get_app()
    consuming = app.control.inspect(timeout=INSPECT_TIMEOUT).active_queues() or {}
    paused = {}
    for queue in queues:
        workers = sorted(
            worker for worker, worker_queues in consuming.items()
            if any(q.get('name') == queue for q in worker_queues or [])
        )
        if not workers:
            continue
        app.control.cancel_consumer(queue, destination=workers, reply=True,
                                    timeout=INSPECT_TIMEOUT)
        paused[queue] = workers
    emit('PAUSED', json.dumps(paused))


def resume(mapping):
    app = get_app()
    resumed = 0
    for queue, workers in mapping.items():
        if not workers:
            continue
        # Workers that were replaced by the update simply do not answer; the
        # new containers consume their queues from the command line.
        app.control.add_consumer(queue, destination=workers, reply=True,
                                 timeout=INSPECT_TIMEOUT)
        resumed += 1
    emit('RESUMED', str(resumed))


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == 'status':
        expected = int(rest[0]) if rest else 0
        paused_queues = set(filter(None, rest[1].split(','))) if len(rest) > 1 else set()
        status(expected, paused_queues)
    elif mode == 'pause':
        pause([q for q in (rest[0] if rest else '').split(',') if q])
    elif mode == 'resume':
        resume(json.loads(rest[0]) if rest else {})
    else:
        print(f'unknown mode: {mode}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
