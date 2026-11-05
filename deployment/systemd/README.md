# systemd autostart for the OK Tools stack

Runs the production Docker Compose stack as a systemd service so it starts on
boot **and only after** its NAS / custom bind-mount host paths are mounted.

Why this matters: if Docker starts the containers before `/mnt/nas` (or another
NAS/export path) is mounted, Docker creates an empty directory at the mount
point and the app silently reads/writes the wrong location. An
`ExecStartPre=` helper waits for those mounts first (accessing the path also
triggers systemd automounts).

`RequiresMountsFor=` is deliberately not used: if the NAS is not reachable yet
at boot, the mount fails once, systemd skips the unit and never retries, and
the site stays down until someone starts it by hand. With the helper the unit
waits up to 5 minutes, then fails and `Restart=on-failure` (every 30s, no start
limit) tries again until the mounts appear.

While waiting, the helper also retries mounts itself: for a path that is still
missing it finds the matching `/etc/fstab` entry (the path or its closest
parent) and runs `systemctl reset-failed` + `systemctl start` on that `.mount`
unit every 30s (`WAIT_MOUNTS_RETRY`). A plain fstab CIFS mount without
`x-systemd.automount` that failed at boot is otherwise never retried by
systemd, and the stack would wait forever. Adding `x-systemd.automount` to such
fstab lines is still recommended.

## Files

- `ok-tools.service` — unit template. `__PRODUCTION_DIR__` and `__DOCKER_BIN__`
  are substituted at install time. `Type=oneshot` + `RemainAfterExit=yes` wraps
  `docker compose up -d` / `down`.
- `ok-tools-wait-mounts.sh` — waits until each given path is on a real mount;
  installed root-owned to `/usr/local/lib/ok-tools/`.
- `../scripts/install-systemd.sh` — renders the unit into
  `/etc/systemd/system/ok-tools.service`, generates the mount dependency drop-in
  from `.env`, then `daemon-reload` + `enable`.

## Install

```bash
sudo deployment/scripts/install-systemd.sh
# or start it right away:
sudo systemctl start ok-tools
```

The main `install.sh` also offers to run this at the end of a fresh install.

### Where the mount paths come from

`install-systemd.sh` reads the production `.env` and collects:

- `NAS_MOUNT_PATH`
- `CUSTOM_MOUNT_1_PATH` … `CUSTOM_MOUNT_10_PATH`

and writes them into
`/etc/systemd/system/ok-tools.service.d/10-mounts.conf` as:

```ini
[Service]
ExecStartPre=/usr/local/lib/ok-tools/ok-tools-wait-mounts.sh /mnt/nas /mnt/austausch_export
```

If a required path is not modelled in `.env` (e.g. an austausch export target),
pass it explicitly:

```bash
sudo EXTRA_MOUNTS="/mnt/austausch_export" deployment/scripts/install-systemd.sh
```

Re-run the script after changing mount paths in `.env`.

### Overrides

- `PRODUCTION_DIR` — production dir (default: `../ok_tools_production`)
- `SERVICE_NAME` — unit name (default: `ok-tools`)
- `EXTRA_MOUNTS` — extra space-separated paths to require

## Verify / operate

```bash
systemctl status ok-tools
systemctl cat ok-tools                                  # confirm drop-in
sudo systemctl start ok-tools
sudo systemctl stop ok-tools
```

> While the unit manages the stack, don't also run the `start.sh` / `stop.sh`
> helpers by hand — both call `docker compose up -d` / `down` and will fight
> over container state.
