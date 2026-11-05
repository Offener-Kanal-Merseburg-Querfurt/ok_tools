#!/bin/bash
# Wait until every given host path sits on a real mount (NAS / custom mounts),
# so the Docker Compose stack never starts on top of an empty mount point.
#
# Used as ExecStartPre= of ok-tools.service. Unlike RequiresMountsFor=, a mount
# that is not ready yet at boot (NAS still booting, network slow) does not make
# systemd skip the stack for good: this script keeps retrying, and if it gives
# up the unit fails and Restart=on-failure runs it again.
#
# A plain fstab mount (no x-systemd.automount) that failed at boot is never
# retried by systemd itself. For such paths the script looks up the fstab
# entry and starts its .mount unit again every WAIT_MOUNTS_RETRY seconds, so
# the stack comes up as soon as the NAS answers.
#
# Usage: ok-tools-wait-mounts.sh PATH [PATH...]
# Environment: WAIT_MOUNTS_TIMEOUT (seconds, default 300)
#              WAIT_MOUNTS_RETRY   (seconds between mount retries, default 30)

set -u

TIMEOUT="${WAIT_MOUNTS_TIMEOUT:-300}"
RETRY="${WAIT_MOUNTS_RETRY:-30}"
INTERVAL=5

# A path counts as mounted when it exists (stat also triggers a systemd
# automount) and the filesystem holding it is neither the root filesystem nor
# a still-untriggered autofs placeholder. Sub-paths of a mount, such as
# /mnt/nas/INBOX, are handled the same way.
is_mounted() {
    local path="$1" target fstype
    # "$path/." forces a lookup inside the directory, which reliably triggers
    # an automount even when the mount point itself is only an autofs stub.
    stat "$path/." >/dev/null 2>&1 || return 1
    target="$(findmnt -n -o TARGET -T "$path" 2>/dev/null | tail -n 1)"
    fstype="$(findmnt -n -o FSTYPE -T "$path" 2>/dev/null | tail -n 1)"
    [ -n "$target" ] && [ "$target" != "/" ] && [ "$fstype" != "autofs" ]
}

# Print the fstab mount point that should provide PATH: PATH itself or its
# closest parent with an fstab entry. Prints nothing when there is none.
fstab_target() {
    local dir="$1"
    while [ -n "$dir" ] && [ "$dir" != "/" ]; do
        if findmnt --fstab -n "$dir" >/dev/null 2>&1; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

# Start the .mount unit of an fstab entry again. Clearing the failed state
# first lets systemd retry a mount that already failed during boot.
retry_mount() {
    local target="$1" unit
    unit="$(systemd-escape --path --suffix=mount "$target")" || return 0
    echo "Retrying mount: $target ($unit)"
    systemctl reset-failed "$unit" >/dev/null 2>&1 || true
    if ! systemctl start --no-block "$unit"; then
        echo "Could not start $unit" >&2
    fi
}

if [ "$#" -eq 0 ]; then
    exit 0
fi

deadline=$(( $(date +%s) + TIMEOUT ))
next_retry=$(( $(date +%s) + RETRY ))
while :; do
    missing=()
    for path in "$@"; do
        is_mounted "$path" || missing+=("$path")
    done
    if [ "${#missing[@]}" -gt 0 ] && [ "$(date +%s)" -ge "$next_retry" ]; then
        retried=" "
        for path in "${missing[@]}"; do
            target="$(fstab_target "$path")" || continue
            case "$retried" in *" $target "*) continue ;; esac
            retried="$retried$target "
            retry_mount "$target"
        done
        next_retry=$(( $(date +%s) + RETRY ))
    fi
    if [ "${#missing[@]}" -eq 0 ]; then
        echo "All mounts ready: $*"
        exit 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "Mounts still not ready after ${TIMEOUT}s: ${missing[*]}" >&2
        exit 1
    fi
    echo "Waiting for mounts: ${missing[*]}"
    sleep "$INTERVAL"
done
