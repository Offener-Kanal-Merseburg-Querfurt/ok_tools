#!/bin/bash
# Generate docker-compose.override.yml based on environment variables
# This allows individual servers to mount custom volumes without modifying git-tracked files

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Try to detect production directory from current working directory or script location
# If script is called from production directory, use that
# Otherwise, try to find it relative to script location
if [ -f "docker-compose.yml" ] || [ -f ".env" ]; then
    PRODUCTION_DIR="$(pwd)"
else
    # Try parent of parent (assuming script is in deployment/scripts/)
    PRODUCTION_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    # If that doesn't work, try to find it
    if [ ! -f "$PRODUCTION_DIR/docker-compose.yml" ] && [ ! -f "$PRODUCTION_DIR/.env" ]; then
        # Look for production directory in common locations
        if [ -d "$(dirname "$SCRIPT_DIR")/../../ok_tools_production" ]; then
            PRODUCTION_DIR="$(dirname "$SCRIPT_DIR")/../../ok_tools_production"
        fi
    fi
fi
OVERRIDE_FILE="$PRODUCTION_DIR/docker-compose.override.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Load .env file if it exists
ENV_FILE="$PRODUCTION_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    print_info "Loading environment variables from $ENV_FILE"
    set -a
    # Use a safer method to load .env file that handles values with spaces
    # This exports variables while ignoring comments and empty lines
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        # Export variable, handling values with spaces and special characters
        if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            var_name="${BASH_REMATCH[1]}"
            var_value="${BASH_REMATCH[2]}"
            # Remove leading/trailing whitespace and quotes if present
            var_value="${var_value#"${var_value%%[![:space:]]*}"}"
            var_value="${var_value%"${var_value##*[![:space:]]}"}"
            var_value="${var_value#\"}"
            var_value="${var_value%\"}"
            var_value="${var_value#\'}"
            var_value="${var_value%\'}"
            # Export the variable
            export "$var_name=$var_value"
        fi
    done < "$ENV_FILE"
    set +a
fi

# Check if we're in the production directory
if [ ! -f "$PRODUCTION_DIR/docker-compose.yml" ] && [ ! -f "$PRODUCTION_DIR/docker-compose.production.yml" ]; then
    print_error "Production directory not found. Expected docker-compose.yml or docker-compose.production.yml in: $PRODUCTION_DIR"
    exit 1
fi

# Start building override file
print_info "Generating docker-compose.override.yml..."

# Use associative arrays to collect volumes per service
declare -A service_volumes

# Services that may need extra configuration generated from .env (beyond volume mounts)
declare -A service_extras

# Services that need access to NAS-backed media paths by default.
MEDIA_SERVICES=(
    "web"
    "celery_worker"
    "celery_download_worker"
    "celery_render_worker"
    "celery_copy_worker"
    "celery_anchor_render_worker"
)

CELERY_SERVICES=(
    "celery_worker"
    "celery_download_worker"
    "celery_render_worker"
    "celery_copy_worker"
    "celery_anchor_render_worker"
    "celery_beat"
)

# Helper: add build args for UID/GID alignment if configured
add_uid_gid_build_args() {
    local service_name="$1"
    # Only add if at least one variable is set (avoid forcing build config unexpectedly)
    if [ -n "${USER_UID:-}" ] || [ -n "${USER_GID:-}" ]; then
        service_extras["$service_name"]="${service_extras["$service_name"]}|build_args"
    fi
}

# Helper: add Celery entrypoint wrapper (diagnostics + permission checks)
add_celery_entrypoint() {
    local service_name="$1"
    service_extras["$service_name"]="${service_extras["$service_name"]}|celery_entrypoint"
}

# Helper: give a long-running transfer worker time for a Celery warm shutdown
add_stop_grace_period() {
    local service_name="$1"
    service_extras["$service_name"]="${service_extras["$service_name"]}|stop_grace"
}

# Function to add volume mount to a service (collects volumes, doesn't write yet)
add_volume_to_service() {
    local service_name=$1
    local host_path=$2
    local container_path=$3
    local mode=${4:-ro}
    
    # Validate paths
    if [ -z "$host_path" ] || [ -z "$container_path" ]; then
        return 1
    fi
    
    # Check if host path exists (warn if not)
    if [ ! -e "$host_path" ]; then
        print_warning "Host path does not exist: $host_path (will be created if needed)"
    fi
    
    # Add volume to service's volume list (store as array-like string)
    local volume_entry="${host_path}:${container_path}:${mode}"
    if [ -z "${service_volumes[$service_name]}" ]; then
        service_volumes[$service_name]="$volume_entry"
    else
        service_volumes[$service_name]="${service_volumes[$service_name]}|${volume_entry}"
    fi
}

# Check for NAS mount
if [ -n "${NAS_MOUNT_PATH:-}" ]; then
    NAS_MODE="${NAS_MOUNT_MODE:-ro}"
    print_info "Adding NAS mount: ${NAS_MOUNT_PATH} -> /mnt/nas (${NAS_MODE})"
    
    # Add to services that may need access to NAS-backed media paths
    for service in "${MEDIA_SERVICES[@]}"; do
        add_volume_to_service "$service" "$NAS_MOUNT_PATH" "/mnt/nas" "$NAS_MODE"
    done
else
    print_info "NAS_MOUNT_PATH not set - skipping NAS mount"
fi

# Check for custom mounts (CUSTOM_MOUNT_1_PATH, CUSTOM_MOUNT_2_PATH, etc.)
MOUNT_COUNT=0
for i in {1..10}; do
    MOUNT_PATH_VAR="CUSTOM_MOUNT_${i}_PATH"
    MOUNT_CONTAINER_VAR="CUSTOM_MOUNT_${i}_CONTAINER_PATH"
    MOUNT_MODE_VAR="CUSTOM_MOUNT_${i}_MODE"
    MOUNT_SERVICES_VAR="CUSTOM_MOUNT_${i}_SERVICES"
    
    MOUNT_PATH="${!MOUNT_PATH_VAR:-}"
    MOUNT_CONTAINER="${!MOUNT_CONTAINER_VAR:-}"
    MOUNT_MODE="${!MOUNT_MODE_VAR:-ro}"
    MOUNT_SERVICES="${!MOUNT_SERVICES_VAR:-$(IFS=,; echo "${MEDIA_SERVICES[*]}")}"
    
    if [ -n "$MOUNT_PATH" ] && [ -n "$MOUNT_CONTAINER" ]; then
        MOUNT_COUNT=$((MOUNT_COUNT + 1))
        print_info "Adding custom mount #${i}: ${MOUNT_PATH} -> ${MOUNT_CONTAINER} (${MOUNT_MODE})"
        
        # Add to specified services (comma-separated)
        IFS=',' read -ra SERVICES <<< "$MOUNT_SERVICES"
        for service in "${SERVICES[@]}"; do
            service=$(echo "$service" | xargs) # trim whitespace
            add_volume_to_service "$service" "$MOUNT_PATH" "$MOUNT_CONTAINER" "$MOUNT_MODE"
        done
    fi
done

if [ $MOUNT_COUNT -eq 0 ] && [ -z "${NAS_MOUNT_PATH:-}" ]; then
    print_info "No custom mounts configured"
fi

# Always consider UID/GID build args (permission alignment for bind mounts)
add_uid_gid_build_args "web"
for service in "${CELERY_SERVICES[@]}"; do
    add_uid_gid_build_args "$service"
done

# Always consider Celery entrypoint (safe even if permissions are already correct)
for service in "${CELERY_SERVICES[@]}"; do
    add_celery_entrypoint "$service"
done

# Transfer workers get a long stop grace period so SIGTERM (update, restart)
# lets the running copy/download finish instead of killing it after 10s.
# The production compose file has the same setting, but an existing
# docker-compose.yml is only replaced on FORCE_OVERWRITE=1, while this
# override is regenerated on every update.
CELERY_TRANSFER_STOP_GRACE_PERIOD="${CELERY_TRANSFER_STOP_GRACE_PERIOD:-30m}"
for service in "celery_copy_worker" "celery_download_worker"; do
    add_stop_grace_period "$service"
done

# Write the override file
# This file may contain both volume mounts AND other server-specific overrides (e.g. UID/GID build args)
#
# We always generate a "services:" map (even if no mounts), because some overrides are not mounts.
cat > "$OVERRIDE_FILE" << 'EOF'
# This file is auto-generated by generate-override.sh
# DO NOT edit manually - it will be overwritten
# To customize mounts and server-specific overrides, set environment variables in .env:
#   NAS_MOUNT_PATH=/mnt/nas
#   NAS_MOUNT_MODE=ro
#   CUSTOM_MOUNT_1_PATH=/path/to/mount1
#   CUSTOM_MOUNT_1_CONTAINER_PATH=/container/path1
#   CUSTOM_MOUNT_1_MODE=ro
#   etc.
#
# UID/GID alignment (recommended for bind mounts permissions):
#   USER_UID=1001
#   USER_GID=1001

services:
EOF

# Build the set of services that need to be written (union of volume services + extras services)
declare -A services_to_write
for s in "${!service_volumes[@]}"; do
    services_to_write["$s"]=1
done
for s in "${!service_extras[@]}"; do
    services_to_write["$s"]=1
done

# If nothing to write (unlikely), write empty services mapping
if [ ${#services_to_write[@]} -eq 0 ]; then
    cat >> "$OVERRIDE_FILE" << 'EOF'
  {}
EOF
    print_info "Override file generated successfully (no overrides configured)"
else
    # Write services in stable order
    for service_name in $(printf "%s\n" "${!services_to_write[@]}" | sort); do
        cat >> "$OVERRIDE_FILE" << EOF
  ${service_name}:
EOF

        extras="${service_extras[$service_name]}"

        # UID/GID build args (only if USER_UID/USER_GID is set in .env)
        if [[ "$extras" == *"|build_args"* ]]; then
            cat >> "$OVERRIDE_FILE" << 'EOF'
    build:
      args:
        USER_UID: ${USER_UID:-1000}
        USER_GID: ${USER_GID:-1000}
EOF
        fi

        # Celery entrypoint wrapper (diagnostics + permission checks)
        if [[ "$extras" == *"|celery_entrypoint"* ]]; then
            cat >> "$OVERRIDE_FILE" << 'EOF'
    entrypoint: ["/app/deployment/entrypoint.celery.sh"]
EOF
        fi

        # Stop grace period for transfer workers (Celery warm shutdown)
        if [[ "$extras" == *"|stop_grace"* ]]; then
            cat >> "$OVERRIDE_FILE" << EOF
    stop_grace_period: ${CELERY_TRANSFER_STOP_GRACE_PERIOD}
EOF
        fi

        # Volume mounts (if any)
        if [ -n "${service_volumes[$service_name]:-}" ]; then
            volumes="${service_volumes[$service_name]}"
            cat >> "$OVERRIDE_FILE" << 'EOF'
    volumes:
EOF
            IFS='|' read -ra VOL_ARRAY <<< "$volumes"
            for vol in "${VOL_ARRAY[@]}"; do
                cat >> "$OVERRIDE_FILE" << EOF
      - ${vol}
EOF
            done
        fi
    done

    print_info "Override file generated successfully"
fi

print_info "Override file location: $OVERRIDE_FILE"
print_info "To apply changes, run: docker compose -f docker-compose.production.yml -f docker-compose.override.yml up -d"
