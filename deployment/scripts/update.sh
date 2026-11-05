#!/bin/bash
set -e

# Update script for OK Tools production environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
PRODUCTION_DIR="$(dirname "$PROJECT_DIR")/ok_tools_production"

# Color functions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}\n"
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info() { echo -e "${BLUE}ℹ $1${NC}"; }

usage() {
    cat <<'USAGE_EOF'
Usage: update.sh [--force] [--no-cache] [--no-pause] [--help]

Flow: backup (.env + database) -> git pull -> JSX build -> docker compose build
(old containers keep serving) -> wait until Celery is idle -> docker compose up -d
-> wait for web to become healthy. Downtime is only the container restart.

  --force      Do not wait for running Celery tasks; restart immediately.
               Workers still get a warm shutdown (stop_grace_period).
  --no-cache   Build Docker images without cache (clean rebuild).
  --no-pause   Do not pause the copy/download/render/anchor_render consumers
               while waiting; new tasks may then start and prolong the wait.

Environment:
  OKTOOLS_UPDATE_WAIT_IDLE      Max seconds to wait for idle Celery (default 3600).
                                On timeout the update aborts; old containers stay up.
  OKTOOLS_UPDATE_WEB_TIMEOUT    Max seconds to wait for web to become healthy
                                after the restart (default 900; it runs migrations).
  OKTOOLS_UPDATE_FORCE=1        Same as --force.
  OKTOOLS_UPDATE_NO_CACHE=1     Same as --no-cache.
  OKTOOLS_UPDATE_NO_PAUSE=1     Same as --no-pause.
  FORCE_OVERWRITE=1             Overwrite docker-compose.yml etc. with the repository version.

Exit code: 0 when every container is running and healthy, non-zero otherwise.
USAGE_EOF
}

# Options. The production wrapper (ok_tools_production/update.sh) forwards its
# arguments; the OKTOOLS_UPDATE_* variables work with older wrappers too.
FORCE_UPDATE="${OKTOOLS_UPDATE_FORCE:-0}"
BUILD_NO_CACHE="${OKTOOLS_UPDATE_NO_CACHE:-0}"
PAUSE_CONSUMERS=1
if [ "${OKTOOLS_UPDATE_NO_PAUSE:-0}" = "1" ]; then
    PAUSE_CONSUMERS=0
fi
while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE_UPDATE=1 ;;
        --no-cache) BUILD_NO_CACHE=1 ;;
        --no-pause) PAUSE_CONSUMERS=0 ;;
        -h|--help) usage; exit 0 ;;
        *) print_error "Unknown option: $1"; usage; exit 2 ;;
    esac
    shift
done
WAIT_IDLE_TIMEOUT="${OKTOOLS_UPDATE_WAIT_IDLE:-3600}"
WEB_HEALTH_TIMEOUT="${OKTOOLS_UPDATE_WEB_TIMEOUT:-900}"
if ! [[ "$WAIT_IDLE_TIMEOUT" =~ ^[0-9]+$ ]] || ! [[ "$WEB_HEALTH_TIMEOUT" =~ ^[0-9]+$ ]]; then
    print_error "OKTOOLS_UPDATE_WAIT_IDLE and OKTOOLS_UPDATE_WEB_TIMEOUT must be whole seconds"
    exit 2
fi

# Interactive only when stdin is a terminal (ssh without -t, cron, CI).
if [ -t 0 ]; then
    INTERACTIVE=1
else
    INTERACTIVE=0
fi

# confirm "<question>" <default y|n>
# Asks on a terminal; without one it prints the question and uses the default,
# so `read` failing on a closed stdin can never abort the script under set -e.
confirm() {
    local question="$1"
    local default="$2"
    local reply=""
    if [ "$INTERACTIVE" = "1" ]; then
        read -p "$question (y/n) " -n 1 -r reply || reply=""
        echo
    else
        print_info "$question -> '$default' (non-interactive)"
        reply="$default"
    fi
    [[ $reply =~ ^[Yy]$ ]]
}

print_header "OK Tools Production Update"

# Ensure a stable Docker build context path ../ok_tools
# This allows cloning the repository into arbitrary directory names (e.g. ok_tools_docker)
# while keeping docker-compose build.context fixed at ../ok_tools
PARENT_DIR="$(dirname "$PROJECT_DIR")"
if [ ! -e "$PARENT_DIR/ok_tools" ]; then
    if ln -s "$PROJECT_DIR" "$PARENT_DIR/ok_tools" 2>/dev/null; then
        print_info "Created symlink for Docker build context: $PARENT_DIR/ok_tools -> $PROJECT_DIR"
    else
        print_warning "Could not create symlink $PARENT_DIR/ok_tools (build.context ../ok_tools must exist)"
    fi
fi

# Check if running as root and warn
if [ "$(id -u)" -eq 0 ]; then
    echo ""
    print_warning "═══════════════════════════════════════════════════════════"
    print_warning "  WARNING: Running as root"
    print_warning "═══════════════════════════════════════════════════════════"
    echo ""
    print_warning "Running update as root is not recommended for security reasons."
    print_info "Best practice: Run as regular user with docker group membership"
    echo ""
    print_info "If you need to fix file permissions, run:"
    echo "  sudo chown -R \$USER:\$USER $PRODUCTION_DIR"
    echo ""
    if ! confirm "Continue update as root anyway?" n; then
        print_info "Update cancelled. Please run as regular user."
        exit 1
    fi
    echo ""
fi

# Get current user info for file ownership
# If running as root via sudo, try to get the original user from SUDO_USER.
# A stale SUDO_USER in a non-root environment must not override the real user.
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
    CURRENT_USER="$SUDO_USER"
    CURRENT_UID=$(id -u "$SUDO_USER" 2>/dev/null || echo "$(id -u)")
    CURRENT_GID=$(id -g "$SUDO_USER" 2>/dev/null || echo "$(id -g)")
    print_info "Detected sudo usage - will use user $CURRENT_USER for file ownership"
else
    CURRENT_USER=$(id -un)
    CURRENT_UID=$(id -u)
    CURRENT_GID=$(id -g)
fi

if [ ! -d "$PRODUCTION_DIR" ]; then
    print_error "Production directory not found at $PRODUCTION_DIR"
    print_info "Please run install.sh first"
    exit 1
fi

# Logging setup - use production directory for logs
LOG_DIR="$PRODUCTION_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/update-$(date +%Y%m%d-%H%M%S).log"

# Create log file and set permissions
touch "$LOG_FILE" 2>/dev/null || {
    print_warning "Cannot create log file at $LOG_FILE, logging to console only"
    LOG_FILE=""
}

if [ -n "$LOG_FILE" ]; then
    chmod 644 "$LOG_FILE" 2>/dev/null || true
    # Redirect output to both terminal and log file
    exec > >(tee -a "$LOG_FILE") 2>&1
    print_info "Log file: $LOG_FILE"
else
    print_info "Logging to console only"
fi

echo ""

# Helper function to escape special characters for sed
escape_for_sed() {
    echo "$1" | sed -e 's/[]\/$*.^[]/\\&/g'
}

# Copy helper: keep existing file, write new version to .new unless forced
copy_as_new_if_changed() {
    local src="$1"
    local dest="$2"
    local label="$3"
    local force="${FORCE_OVERWRITE:-0}"

    if [ ! -f "$src" ]; then
        print_warning "Source file not found: $src"
        return 1
    fi

    if [ "$force" = "1" ]; then
        cp -f "$src" "$dest"
        print_info "$label overwritten (FORCE_OVERWRITE=1)"
        return 0
    fi

    if [ ! -f "$dest" ]; then
        cp "$src" "$dest"
        print_success "$label copied"
        return 0
    fi

    if cmp -s "$src" "$dest"; then
        print_info "$label unchanged"
        return 0
    fi

    local new_path="${dest}.new"
    cp "$src" "$new_path"
    print_warning "$label differs; kept existing, new saved as $(basename "$new_path")"
    print_warning "To apply it automatically, re-run with: FORCE_OVERWRITE=1 ./update.sh"
    return 0
}

apply_required_compose_service_update() {
    local service_name="$1"
    local compose_file="$PRODUCTION_DIR/docker-compose.yml"
    local new_compose_file="$PRODUCTION_DIR/docker-compose.yml.new"

    if [ "${OKTOOLS_KEEP_EXISTING_COMPOSE:-0}" = "1" ]; then
        print_warning "OKTOOLS_KEEP_EXISTING_COMPOSE=1 set; not auto-applying compose changes for $service_name"
        return 0
    fi

    if [ ! -f "$new_compose_file" ]; then
        return 0
    fi

    if [ ! -f "$compose_file" ]; then
        return 0
    fi

    if ! grep -qE "^[[:space:]]{2}${service_name}:" "$new_compose_file"; then
        return 0
    fi

    if grep -qE "^[[:space:]]{2}${service_name}:" "$compose_file"; then
        return 0
    fi

    local backup_file
    backup_file="$compose_file.backup.$(date +%Y%m%d_%H%M%S)"
    print_warning "Current docker-compose.yml is missing required service: $service_name"
    print_info "Backing up current docker-compose.yml to $(basename "$backup_file")"
    cp "$compose_file" "$backup_file"
    mv "$new_compose_file" "$compose_file"
    print_success "Applied updated docker-compose.yml with required service: $service_name"
}

# Function to validate .env file (from install.sh)
validate_env_file() {
    local env_file="$1"
    local errors=0
    local warnings=0
    
    echo ""
    echo "Validating .env file..."
    echo "======================"
    
    # Check if file exists
    if [ ! -f "$env_file" ]; then
        echo "❌ ERROR: .env file not found at $env_file"
        return 1
    fi
    
    # Check file permissions
    if [ ! -r "$env_file" ]; then
        echo "❌ ERROR: Cannot read .env file at $env_file (permission denied)"
        echo "   File owner: $(ls -ld "$env_file" | awk '{print $3":"$4}')"
        echo "   Current user: $(whoami)"
        echo "   Try: sudo chmod 644 $env_file"
        echo "   Or: sudo chown $(whoami):$(whoami) $env_file"
        return 1
    fi
    
    # Critical variables that must exist and have values
    local critical_vars=(
        "POSTGRES_PASSWORD"
        "POSTGRES_DB"
        "POSTGRES_USER"
        "DATABASE_URL"
        "DJANGO_SECRET_KEY"
        "ALLOWED_HOSTS"
    )
    
    # Check each critical variable
    for var in "${critical_vars[@]}"; do
        # Extract the value for this variable - try with current user first, then sudo if needed
        local value
        value=$(grep "^${var}=" "$env_file" 2>/dev/null | head -1 | cut -d'=' -f2-)

        # If grep found nothing, try with sudo (if available)
        if [ -z "$value" ]; then
            if command -v sudo >/dev/null 2>&1; then
                value=$(sudo grep "^${var}=" "$env_file" 2>/dev/null | head -1 | cut -d'=' -f2-)
            fi
        fi
        
        # Check if variable exists
        if [ -z "$value" ]; then
            echo "❌ ERROR: $var is missing or empty (or cannot read file)"
            errors=$((errors+1))
            continue
        fi
        
        # Check if value is a placeholder
        if [[ "$value" == *"__REPLACE_ME__"* ]]; then
            echo "❌ ERROR: $var still contains __REPLACE_ME__ placeholder"
            errors=$((errors+1))
            continue
        fi
        
        # Check if value contains inline comments
        if [[ "$value" =~ [[:space:]]+# ]]; then
            echo "⚠️  WARNING: $var contains inline comment - value may be malformed"
            warnings=$((warnings+1))
        fi
        
        # Special validation for specific variables
        case "$var" in
            "DATABASE_URL")
                if [[ ! "$value" =~ ^postgresql:// ]]; then
                    echo "❌ ERROR: DATABASE_URL must start with postgresql://"
                    errors=$((errors+1))
                fi
                ;;
            "ALLOWED_HOSTS")
                if [[ -z "$value" ]] || [[ "$value" == "localhost" ]]; then
                    echo "⚠️  WARNING: ALLOWED_HOSTS should include your domain/IP"
                    warnings=$((warnings+1))
                fi
                ;;
        esac
        
        echo "✓ $var: OK"
    done
    
    # Check for concatenated lines (common issue) - IMPROVED DETECTION
    # Only flag as error if it's clearly a concatenation of separate variables
    local concatenated
    concatenated=$(grep -cE '^[A-Z_][A-Z0-9_]*=[^=]*[A-Z_][A-Z0-9_]*=' "$env_file" || true)
    if [ "$concatenated" -gt 0 ]; then
        echo "❌ ERROR: Found $concatenated line(s) with concatenated variables"
        echo "   This usually means line breaks are missing in .env file"
        errors=$((errors+1))
        
        # Show problematic lines
        echo "   Problematic lines:"
        grep -E '^[A-Z_][A-Z0-9_]*=[^=]*[A-Z_][A-Z0-9_]*=' "$env_file" | head -5 | sed 's/^/   /'
    fi
    
    # Summary
    echo ""
    echo "Validation Summary:"
    echo "==================="
    echo "Errors: $errors"
    echo "Warnings: $warnings"
    
    if [ $errors -gt 0 ]; then
        echo ""
        echo "❌ Validation FAILED - please fix errors before proceeding"
        return 1
    elif [ $warnings -gt 0 ]; then
        echo ""
        echo "⚠️  Validation passed with warnings - review before production use"
        return 0
    else
        echo ""
        echo "✅ Validation PASSED - .env file is properly configured"
        return 0
    fi
}

# IMPROVED Function to detect and repair corrupted .env files
# Only repairs actual corruption, not legitimate values with '='
repair_env_file() {
    local env_file="$PRODUCTION_DIR/.env"
    
    if [ ! -f "$env_file" ]; then
        echo "Warning: .env file not found at $env_file"
        return 1
    fi
    
    # Check file permissions
    if [ ! -r "$env_file" ]; then
        echo "Warning: Cannot read .env file at $env_file (permission denied)"
        echo "   File owner: $(ls -ld "$env_file" 2>/dev/null | awk '{print $3":"$4}' || echo 'unknown')"
        echo "   Current user: $(whoami)"
        return 1
    fi
    
    # Check for corruption pattern: ONLY flag clear concatenations of separate variables
    # Pattern: KEY1=VALUE1KEY2=VALUE2 (no space between VALUE1 and KEY2)
    local corrupted_lines
    corrupted_lines=$(grep -cE '^[A-Z_][A-Z0-9_]*=[^=]*[A-Z_][A-Z0-9_]*=' "$env_file" 2>/dev/null || true)
    corrupted_lines=${corrupted_lines:-0}
    
    if [ "$corrupted_lines" -gt 0 ]; then
        echo "Detected corruption in .env file ($corrupted_lines corrupted lines)"
        echo "Creating backup..."
        cp "$env_file" "$env_file.backup.$(date +%Y%m%d_%H%M%S)"
        
        echo "Repairing .env file..."
        
        # Create temporary file for repaired content
        local temp_file="/tmp/repaired_env.tmp"
        
        # Process each line to fix concatenated variables
        while IFS= read -r line; do
            # Skip comments and empty lines
            if [[ $line =~ ^# ]] || [[ -z "$line" ]]; then
                echo "$line" >> "$temp_file"
                continue
            fi
            
            # Check if line contains ACTUAL concatenated variables (not just = in values)
            if [[ $line =~ ^([^=]+)=(.*) ]]; then
                local key="${BASH_REMATCH[1]}"
                local value="${BASH_REMATCH[2]}"
                
                # Check if this is actually a concatenation by looking for pattern: VALUEKEY2=
                # where KEY2 starts with uppercase letter and is followed by =
                if [[ $value =~ ([^=]*[A-Z_][A-Z0-9_]*)=(.*)$ ]]; then
                    # This is a concatenation, split it
                    local first_value="${BASH_REMATCH[1]}"
                    local remaining="${BASH_REMATCH[2]}"
                    
                    # Write the first key-value pair
                    echo "$key=$first_value" >> "$temp_file"
                    
                    # Try to extract the second key-value pair
                    if [[ $remaining =~ ^([^=]+)=(.*)$ ]]; then
                        local second_key="${BASH_REMATCH[1]}"
                        local second_value="${BASH_REMATCH[2]}"
                        echo "$second_key=$second_value" >> "$temp_file"
                    fi
                else
                    # Line is not corrupted, write as-is
                    echo "$line" >> "$temp_file"
                fi
            else
                # Line is not corrupted, write as-is
                echo "$line" >> "$temp_file"
            fi
        done < "$env_file"
        
        # Replace original file with repaired version
        mv "$temp_file" "$env_file"
        chmod 600 "$env_file"
        
        # Set ownership if not root and we know the current user
        if [ "$(id -u)" -ne 0 ] && [ -n "${CURRENT_UID:-}" ]; then
            chown "$CURRENT_UID:$CURRENT_GID" "$env_file" 2>/dev/null || true
        fi
        
        echo "✓ .env file repaired successfully"
        return 0
    else
        echo "✓ .env file appears to be valid"
        return 0
    fi
}

# Function to fix file permissions if needed
fix_permissions() {
    local target_dir="$1"
    
    if [ ! -d "$target_dir" ]; then
        return 1
    fi
    
    # Check if running as root - if so, try to fix ownership
    if [ "$(id -u)" -eq 0 ]; then
        print_info "Running as root - cannot automatically fix ownership"
        return 1
    fi
    
    # Check if files are owned by different user
    local dir_owner
    dir_owner=$(stat -c '%U' "$target_dir" 2>/dev/null || stat -f '%Su' "$target_dir" 2>/dev/null || echo "")
    if [ -n "$dir_owner" ] && [ "$dir_owner" != "$CURRENT_USER" ] && [ "$dir_owner" != "root" ]; then
        print_warning "Production directory is owned by $dir_owner, but running as $CURRENT_USER"
        print_info "Attempting to fix ownership..."
        
        # Try to fix with sudo if available
        if command -v sudo >/dev/null 2>&1; then
            if sudo chown -R "$CURRENT_UID:$CURRENT_GID" "$target_dir" 2>/dev/null; then
                print_success "Fixed ownership of $target_dir to $CURRENT_USER"
                return 0
            else
                print_warning "Could not fix ownership - may need manual intervention"
                return 1
            fi
        else
            print_warning "sudo not available - cannot fix ownership automatically"
            return 1
        fi
    fi
    
    return 0
}

# Try to fix permissions if needed (but don't fail if we can't)
fix_permissions "$PRODUCTION_DIR" || true

# Check and repair .env file if needed
if ! repair_env_file; then
    print_info "Note: .env file check completed (or skipped due to permissions)"
fi

# Validate .env file before proceeding
ENV_FILE="$PRODUCTION_DIR/.env"
if [ ! -r "$ENV_FILE" ]; then
    echo ""
    print_error "Cannot read .env file at $ENV_FILE"
    echo ""
    print_info "File information:"
    ls -ld "$ENV_FILE" 2>/dev/null || echo "   File not found or cannot access"
    echo "   Current user: $CURRENT_USER"
    echo ""
    
    # Try to fix permissions automatically
    if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
        print_info "Attempting to fix .env file permissions..."
        if sudo chmod 644 "$ENV_FILE" 2>/dev/null && sudo chown "$CURRENT_UID:$CURRENT_GID" "$ENV_FILE" 2>/dev/null; then
            chmod 600 "$ENV_FILE" 2>/dev/null || true
            print_success "Fixed .env file permissions"
        else
            print_warning "Could not automatically fix permissions"
        fi
    fi
    
    # Check again after attempt to fix
    if [ ! -r "$ENV_FILE" ]; then
        print_warning "To fix permissions manually, run one of these commands:"
        echo "   sudo chmod 644 $ENV_FILE && sudo chown $CURRENT_USER:$CURRENT_USER $ENV_FILE"
        echo "   sudo chown $CURRENT_USER:$CURRENT_USER $ENV_FILE"
        echo ""
        if ! confirm "Do you want to continue without .env validation?" n; then
            print_info "Update cancelled. Please fix .env file permissions first."
            exit 1
        fi
        print_warning "Continuing without .env validation - this may cause issues later"
    fi
elif ! validate_env_file "$ENV_FILE"; then
    echo ""
    print_warning ".env file validation failed. Please review and fix errors"
    if ! confirm "Do you want to continue anyway?" n; then
        print_info "Update cancelled"
        exit 1
    fi
fi

# Create .env backup with timestamp before update
print_info "Creating .env backup with timestamp..."
ENV_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp "$PRODUCTION_DIR/.env" "$PRODUCTION_DIR/.env.backup.$ENV_TIMESTAMP" 2>/dev/null || true
if [ -f "$PRODUCTION_DIR/.env.backup.$ENV_TIMESTAMP" ]; then
    print_success "Created .env backup: .env.backup.$ENV_TIMESTAMP"
else
    print_warning "Could not create .env backup"
fi

# Function to rotate .env backups - keep only last 7
rotate_env_backups() {
    local env_backup_dir="$PRODUCTION_DIR"
    
    print_info "Rotating .env backups (keeping last 7)..."
    
    # Find all .env backup files, oldest first: the names end in a
    # YYYYMMDD_HHMMSS timestamp, so name order is chronological and the
    # removal loop below must start from the beginning of the list.
    local all_env_backups=()
    while IFS= read -r -d '' file; do
        all_env_backups+=("$file")
    done < <(find "$env_backup_dir" -maxdepth 1 -type f -name ".env.backup.*" -print0 2>/dev/null | sort -z)
    
    local backup_count=${#all_env_backups[@]}
    
    if [ "$backup_count" -gt 7 ]; then
        # Calculate how many backups to remove (keep last 7)
        local remove_count=$((backup_count - 7))
        print_info "Found $backup_count .env backups, removing oldest $remove_count"
        
        # Remove the oldest backups
        for ((i = 0; i < remove_count; i++)); do
            local backup_to_remove="${all_env_backups[$i]}"
            if [ -f "$backup_to_remove" ]; then
                rm -f "$backup_to_remove"
                print_info "Removed old .env backup: $(basename "$backup_to_remove")"
            fi
        done
        
        print_success ".env backup rotation completed (kept 7 most recent)"
    elif [ "$backup_count" -gt 0 ]; then
        print_success ".env backup rotation completed (found $backup_count, keeping all)"
    else
        print_info "No .env backup files found for rotation"
    fi
}

# Run .env backup rotation immediately after creating the new backup
rotate_env_backups

# Create backup before update
print_header "Creating Backup Before Update"
BACKUP_DIR="$PRODUCTION_DIR/backups/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

print_info "Backing up database..."
cd "$PRODUCTION_DIR"

# Check if database container is running
if ! docker compose ps db | grep -q "Up"; then
    print_warning "Database container is not running, skipping database backup"
else
    # Wait for database to be ready (up to 30 seconds)
    print_info "Waiting for database to be ready..."
    DB_READY=false
    for i in {1..30}; do
        if docker compose exec -T db pg_isready -U oktools > /dev/null 2>&1; then
            DB_READY=true
            break
        fi
        if [ $i -lt 30 ]; then
            sleep 1
        fi
    done
    
    if [ "$DB_READY" = false ]; then
        print_warning "Database is not ready after 30 seconds, skipping backup"
        print_info "Database may still be starting up. Backup will be skipped for safety."
    else
        # Attempt to create database backup
        print_info "Creating database backup..."
        # Create backup and capture both stdout and stderr
        if docker compose exec -T db pg_dump -U oktools oktools > "$BACKUP_DIR/database.sql" 2>"$BACKUP_DIR/database_backup_error.log"; then
            BACKUP_EXIT_CODE=0
        else
            BACKUP_EXIT_CODE=$?
        fi
        
        # Check if backup was successful
        if [ $BACKUP_EXIT_CODE -eq 0 ] && [ -f "$BACKUP_DIR/database.sql" ] && [ -s "$BACKUP_DIR/database.sql" ]; then
            BACKUP_SIZE=$(du -h "$BACKUP_DIR/database.sql" | cut -f1)
            print_success "Database backup created successfully (size: $BACKUP_SIZE)"
            # Remove error log if backup was successful
            rm -f "$BACKUP_DIR/database_backup_error.log" 2>/dev/null || true
        else
            print_warning "Database backup failed"
            # Show error details if error log exists and has content
            if [ -f "$BACKUP_DIR/database_backup_error.log" ] && [ -s "$BACKUP_DIR/database_backup_error.log" ]; then
                print_info "  Error details:"
                head -5 "$BACKUP_DIR/database_backup_error.log" | sed 's/^/    /'
            fi
            # Remove empty backup file
            if [ -f "$BACKUP_DIR/database.sql" ] && [ ! -s "$BACKUP_DIR/database.sql" ]; then
                rm -f "$BACKUP_DIR/database.sql"
                print_info "  Removed empty backup file"
            fi
            print_info "  You may want to create a manual backup:"
            print_info "    docker compose exec -T db pg_dump -U oktools oktools > backup.sql"
        fi
    fi
fi

print_info "Backing up configuration..."
cp "$PRODUCTION_DIR/.env" "$BACKUP_DIR/.env.backup" 2>/dev/null || true
cp "$PRODUCTION_DIR/docker-compose.yml" "$BACKUP_DIR/docker-compose.yml.backup" 2>/dev/null || true
print_success "Configuration backup created"

# Backup rotation for general backup directories - keep only last 5
print_info "Rotating general backups (keeping last 5)..."
# Only the backup-YYYYMMDD-HHMMSS directories created by this script are
# rotated here. The nightly backup-YYYY-MM-DD_HH-MM-SS.sql.gz dumps in the same
# folder belong to the scheduled DB backup and have their own retention.
UPDATE_BACKUPS=()
while IFS= read -r -d '' dir; do
    UPDATE_BACKUPS+=("$dir")
done < <(find "$PRODUCTION_DIR/backups" -mindepth 1 -maxdepth 1 -type d \
    -name 'backup-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]' \
    -print0 2>/dev/null | sort -z)
BACKUP_COUNT=${#UPDATE_BACKUPS[@]}
if [ "$BACKUP_COUNT" -gt 5 ]; then
    for ((i = 0; i < BACKUP_COUNT - 5; i++)); do
        rm -rf "${UPDATE_BACKUPS[$i]}"
        print_info "Removed old backup: $(basename "${UPDATE_BACKUPS[$i]}")"
    done
fi
print_success "General backup rotation completed (kept 5 most recent)"

# Function to create local update.sh script in production directory
create_local_update_script() {
    local local_update_script="$PRODUCTION_DIR/update.sh"
    
    # Check if script already exists
    if [ -f "$local_update_script" ]; then
        print_info "Local update script already exists at $local_update_script"
        # Older wrappers dropped their arguments (--force, --no-cache). The
        # wrapper has already exec'd into this script, so rewriting it is safe.
        if grep -qxF 'exec "$MAIN_UPDATE_SCRIPT"' "$local_update_script" 2>/dev/null; then
            local patched_wrapper="${local_update_script}.tmp.$$"
            if sed 's|^exec "\$MAIN_UPDATE_SCRIPT"$|exec "$MAIN_UPDATE_SCRIPT" "$@"|' "$local_update_script" > "$patched_wrapper" 2>/dev/null \
                && chmod +x "$patched_wrapper" \
                && mv -f "$patched_wrapper" "$local_update_script"; then
                print_success "Local update script now forwards its arguments"
            else
                rm -f "$patched_wrapper" 2>/dev/null || true
                print_warning "Could not patch $local_update_script to forward arguments; use OKTOOLS_UPDATE_* variables instead"
            fi
        fi
        # Verify it's executable
        if [ ! -x "$local_update_script" ]; then
            print_info "Making local update script executable..."
            chmod +x "$local_update_script" 2>/dev/null || sudo chmod +x "$local_update_script" 2>/dev/null || true
        fi
        return 0
    fi
    
    print_info "Creating local update.sh script in production directory..."
    print_info "Target: $local_update_script"
    
    # Ensure production directory exists and is writable
    if [ ! -d "$PRODUCTION_DIR" ]; then
        print_error "Production directory does not exist: $PRODUCTION_DIR"
        return 1
    fi
    
    # Determine project directory for the script
    local project_dir_for_script="$PROJECT_DIR"
    print_info "Project directory: $project_dir_for_script"
    
    # Check write permissions and determine creation method
    local need_sudo=false
    local current_uid_check
    current_uid_check=$(id -u)
    print_info "Current UID: $current_uid_check, Current user: $(whoami)"
    
    if [ "$current_uid_check" -eq 0 ]; then
        # Running as root - can write directly
        need_sudo=false
        print_info "Running as root - will create file directly"
    elif [ -w "$PRODUCTION_DIR" ]; then
        # Have write permission - can write directly
        need_sudo=false
        print_info "Have write permission - will create file directly"
    else
        # No write permission - need sudo
        need_sudo=true
        print_info "No write permission - will use sudo to create file"
        if ! command -v sudo >/dev/null 2>&1; then
            print_error "Cannot create local update script - no write permission and sudo not available"
            print_info "Production directory: $PRODUCTION_DIR"
            print_info "Current user: $(whoami)"
            print_info "Directory owner: $(stat -c '%U' "$PRODUCTION_DIR" 2>/dev/null || stat -f '%Su' "$PRODUCTION_DIR" 2>/dev/null || echo 'unknown')"
            return 1
        fi
    fi
    
    # Create the script content
    local script_content
    script_content=$(cat <<'SCRIPT_EOF'
#!/bin/bash
# Local update wrapper script for OK Tools production environment
# This script updates the code from git and then calls the main update script

set -e

# Get script directory and project directory
PRODUCTION_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="PROJECT_DIR_PLACEHOLDER"

# Try to find project directory if default path doesn't exist
if [ ! -d "$PROJECT_DIR" ] || [ ! -f "$PROJECT_DIR/deployment/scripts/update.sh" ]; then
    # Try to find project directory by looking for deployment/scripts/update.sh
    # Search in parent directory and common locations
    PARENT_DIR="$(dirname "$PRODUCTION_DIR")"
    for possible_dir in "$PARENT_DIR"/*; do
        if [ -d "$possible_dir" ] && [ -f "$possible_dir/deployment/scripts/update.sh" ]; then
            PROJECT_DIR="$possible_dir"
            break
        fi
    done
fi

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: Project directory not found. Expected at: PROJECT_DIR_PLACEHOLDER"
    echo "Please check your installation or set PROJECT_DIR environment variable."
    exit 1
fi

# Check if main update script exists
MAIN_UPDATE_SCRIPT="$PROJECT_DIR/deployment/scripts/update.sh"
if [ ! -f "$MAIN_UPDATE_SCRIPT" ]; then
    echo "Error: Main update script not found at $MAIN_UPDATE_SCRIPT"
    exit 1
fi

# Create backup archive of PROJECT_DIR before updating
echo "Creating backup archive of project directory before update..."
BACKUP_ARCHIVE_DIR="$PRODUCTION_DIR/backups/code_backups"
mkdir -p "$BACKUP_ARCHIVE_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="code_backup_$TIMESTAMP.tar.gz"
ARCHIVE_PATH="$BACKUP_ARCHIVE_DIR/$ARCHIVE_NAME"

# Create archive excluding unnecessary files
cd "$(dirname "$PROJECT_DIR")"
PROJECT_BASENAME=$(basename "$PROJECT_DIR")
tar -czf "$ARCHIVE_PATH" \\
    --exclude="$PROJECT_BASENAME/venv" \\
    --exclude="$PROJECT_BASENAME/__pycache__" \\
    --exclude="$PROJECT_BASENAME/**/__pycache__" \\
    --exclude="$PROJECT_BASENAME/.git" \\
    --exclude="$PROJECT_BASENAME/node_modules" \\
    --exclude="$PROJECT_BASENAME/.pytest_cache" \\
    --exclude="$PROJECT_BASENAME/.mypy_cache" \\
    --exclude="$PROJECT_BASENAME/*.pyc" \\
    --exclude="$PROJECT_BASENAME/**/*.pyc" \\
    --exclude="$PROJECT_BASENAME/staticfiles" \\
    --exclude="$PROJECT_BASENAME/media" \\
    --exclude="$PROJECT_BASENAME/logs" \\
    "$PROJECT_BASENAME" 2>/dev/null || {
    echo "Warning: Failed to create backup archive, continuing anyway..."
}

if [ -f "$ARCHIVE_PATH" ]; then
    ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
    echo "✓ Backup archive created: $ARCHIVE_NAME ($ARCHIVE_SIZE)"
    
    # Rotate old backups - keep only last 5
    OLD_BACKUPS=$(ls -1t "$BACKUP_ARCHIVE_DIR"/code_backup_*.tar.gz 2>/dev/null | tail -n +6)
    if [ -n "$OLD_BACKUPS" ]; then
        echo "$OLD_BACKUPS" | xargs rm -f 2>/dev/null || true
        echo "✓ Removed old backup archives (kept 5 most recent)"
    fi
else
    echo "⚠ Warning: Backup archive was not created"
fi

# Change to project directory and pull latest code
echo "Updating code from git repository..."
cd "$PROJECT_DIR"
git pull

# Call the main update script with flag indicating it was called from local script
echo "Running update script..."
export LOCAL_UPDATE_CALLED=1
exec "$MAIN_UPDATE_SCRIPT" "$@"
SCRIPT_EOF
)
    
    # Replace placeholder with actual project directory
    script_content="${script_content//PROJECT_DIR_PLACEHOLDER/$project_dir_for_script}"
    
    # Create the script file
    if [ "$need_sudo" = true ]; then
        print_info "Creating local update script with sudo (permission required)..."
        if ! echo "$script_content" | sudo tee "$local_update_script" > /dev/null || [ ! -f "$local_update_script" ]; then
            print_error "Failed to create local update script with sudo"
            return 1
        fi
        sudo chmod +x "$local_update_script" 2>/dev/null || true
    else
        print_info "Creating local update script..."
        if ! echo "$script_content" > "$local_update_script" || [ ! -f "$local_update_script" ]; then
            print_error "Failed to create local update script"
            return 1
        fi
        chmod +x "$local_update_script" 2>/dev/null || true
    fi
    
    # Set ownership if we know the intended user (even if running as root via sudo)
    if [ -n "${CURRENT_UID:-}" ] && [ "$CURRENT_UID" != "0" ]; then
        if [ "$need_sudo" = true ] || [ "$(id -u)" -eq 0 ]; then
            sudo chown "$CURRENT_UID:$CURRENT_GID" "$local_update_script" 2>/dev/null || true
        else
            chown "$CURRENT_UID:$CURRENT_GID" "$local_update_script" 2>/dev/null || true
        fi
        print_info "Set ownership of local update script to user $CURRENT_USER (UID: $CURRENT_UID)"
    fi
    
    # Verify file was created successfully
    if [ -f "$local_update_script" ] && [ -x "$local_update_script" ]; then
        print_success "Local update script created at $local_update_script"
        print_info "You can now use: $local_update_script"
        return 0
    else
        print_error "Failed to create or verify local update script at $local_update_script"
        if [ -f "$local_update_script" ]; then
            print_warning "File exists but is not executable, attempting to fix..."
            chmod +x "$local_update_script" 2>/dev/null || sudo chmod +x "$local_update_script" 2>/dev/null || true
        fi
        return 1
    fi
}

# Pull latest code FIRST (only if called directly, not from local script)
# Check if we're being called from local script by checking caller
if [ -z "${LOCAL_UPDATE_CALLED:-}" ]; then
    print_info "Pulling latest code from repository..."
    cd "$PROJECT_DIR"
    
    # Check if this is a git repository
    if [ ! -d ".git" ]; then
        print_warning "Not a git repository - skipping git pull"
        print_info "To enable updates from git, initialize repository: git init && git remote add origin <url>"
    elif ! git pull 2>&1; then
        GIT_PULL_EXIT=$?
        print_warning "git pull failed (exit code: $GIT_PULL_EXIT)"
        print_info "Possible reasons:"
        print_info "  - No internet connection"
        print_info "  - Git remote not configured (run: git remote add origin <url>)"
        print_info "  - Merge conflicts (resolve manually and retry)"
        print_info "  - Authentication required (configure git credentials)"
        echo ""
        if ! confirm "Continue update anyway?" n; then
            print_info "Update cancelled. Please fix git issues and retry."
            exit 1
        fi
        print_warning "Continuing update without git pull - using current code"
    else
        print_success "Code updated from repository"
    fi
fi

# Check and create local update script AFTER git pull (so we have latest version)
if ! create_local_update_script; then
    print_warning "Failed to create local update script, but continuing with update..."
    print_info "You can create it manually later or run update script directly from project directory"
fi

# Verify that template files exist after git pull
print_info "Verifying template files..."
TEMPLATE_INDEX="$PROJECT_DIR/ok_tools/templates/admin/index.html"
TEMPLATE_NAV="$PROJECT_DIR/ok_tools/templates/admin/nav_sidebar.html"

if [ ! -f "$TEMPLATE_INDEX" ]; then
    print_warning "Template file not found: $TEMPLATE_INDEX"
    print_info "Checking git status..."
    cd "$PROJECT_DIR"
    git status ok_tools/templates/admin/ || true
    print_info "Attempting to restore from git..."
    git checkout HEAD -- ok_tools/templates/admin/index.html 2>/dev/null || print_warning "Could not restore index.html from git"
fi

if [ ! -f "$TEMPLATE_NAV" ]; then
    print_warning "Template file not found: $TEMPLATE_NAV"
    print_info "Attempting to restore from git..."
    cd "$PROJECT_DIR"
    git checkout HEAD -- ok_tools/templates/admin/nav_sidebar.html 2>/dev/null || print_warning "Could not restore nav_sidebar.html from git"
fi

# Verify files exist now
if [ -f "$TEMPLATE_INDEX" ] && [ -f "$TEMPLATE_NAV" ]; then
    print_success "Template files verified: index.html and nav_sidebar.html exist"
else
    print_error "Template files are missing - Docker build may fail or use old templates"
    print_info "Files should be at:"
    print_info "  - $TEMPLATE_INDEX"
    print_info "  - $TEMPLATE_NAV"
    ls -la "$PROJECT_DIR/ok_tools/templates/admin/" 2>/dev/null || print_warning "Template directory not found"
fi

# Update docker-compose files and configs in production directory
print_info "Updating docker-compose files and configs..."
cd "$PROJECT_DIR"

# Determine which docker-compose file to use based on existing installation
# Enhanced detection logic from install.sh
INSTALL_TYPE=""
if grep -q "^DOMAIN_NAME=" "$PRODUCTION_DIR/.env" && [ ! -z "$(grep '^DOMAIN_NAME=' "$PRODUCTION_DIR/.env" | cut -d'=' -f2)" ]; then
    print_info "Detected: Production with Nginx and SSL"
    INSTALL_TYPE="1"
    copy_as_new_if_changed "deployment/docker-compose.production.yml" "$PRODUCTION_DIR/docker-compose.yml" "docker-compose.yml"
    copy_as_new_if_changed "deployment/nginx.conf.template" "$PRODUCTION_DIR/nginx.conf.template" "nginx.conf.template"
    # Ensure deployment directory exists
    mkdir -p "$PRODUCTION_DIR/deployment" 2>/dev/null || sudo mkdir -p "$PRODUCTION_DIR/deployment" 2>/dev/null || true
    # Move file from root to deployment/ if it exists in wrong location (fix for old installations)
    if [ -f "$PRODUCTION_DIR/99-custom-nginx-config.sh" ] && [ ! -f "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" ]; then
        print_info "Moving 99-custom-nginx-config.sh from root to deployment/ directory"
        if mv "$PRODUCTION_DIR/99-custom-nginx-config.sh" "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null; then
            print_success "File moved successfully"
        elif command -v sudo >/dev/null 2>&1; then
            sudo mv "$PRODUCTION_DIR/99-custom-nginx-config.sh" "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null && \
            sudo chown "$CURRENT_UID:$CURRENT_GID" "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null || true
            print_success "File moved with sudo"
        else
            print_warning "Cannot move file - please manually move: mv $PRODUCTION_DIR/99-custom-nginx-config.sh $PRODUCTION_DIR/deployment/99-custom-nginx-config.sh"
        fi
    fi
    # Remove directory if it exists instead of file (fix for incorrect previous installations)
    if [ -d "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" ]; then
        print_warning "Removing directory that should be a file: $PRODUCTION_DIR/deployment/99-custom-nginx-config.sh"
        rm -rf "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null || {
            if command -v sudo >/dev/null 2>&1; then
                sudo rm -rf "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null || {
                    print_error "Cannot remove directory - insufficient permissions even with sudo"
                    print_info "Please manually remove: sudo rm -rf $PRODUCTION_DIR/deployment/99-custom-nginx-config.sh"
                }
            else
                print_error "Cannot remove directory - insufficient permissions and sudo not available"
                print_info "Please manually remove: rm -rf $PRODUCTION_DIR/deployment/99-custom-nginx-config.sh (as root)"
            fi
        }
    fi
    # Copy the nginx entrypoint script into place.
    #
    # deployment/ is usually root-owned (the installer creates it with sudo), so
    # a plain cp fails for a non-root operator and the sudo fallback then blocks
    # on a password it cannot read from a non-interactive shell. Under `set -e`
    # that aborted the entire update - and did so while copying a file that was
    # already byte-identical, which is how the 2026-08-13 production update died
    # halfway through. So: skip when unchanged, and only reach for sudo when it
    # actually works without a prompt.
    NGINX_ENTRYPOINT_SRC="$PROJECT_DIR/deployment/nginx-entrypoint.sh"
    NGINX_ENTRYPOINT_DEST="$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh"
    if cmp -s "$NGINX_ENTRYPOINT_SRC" "$NGINX_ENTRYPOINT_DEST" 2>/dev/null; then
        print_info "nginx entrypoint script already up to date"
    elif cp -f "$NGINX_ENTRYPOINT_SRC" "$NGINX_ENTRYPOINT_DEST" 2>/dev/null; then
        chmod +x "$NGINX_ENTRYPOINT_DEST" 2>/dev/null || true
        print_success "nginx entrypoint script updated"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo cp -f "$NGINX_ENTRYPOINT_SRC" "$NGINX_ENTRYPOINT_DEST"
        sudo chmod +x "$NGINX_ENTRYPOINT_DEST"
        print_success "nginx entrypoint script updated (via sudo)"
    else
        print_error "Cannot update the nginx entrypoint script:"
        print_error "  $NGINX_ENTRYPOINT_DEST"
        print_info "The file differs from the repository version but is not writable,"
        print_info "and sudo is not available without a password prompt."
        print_info "Fix the ownership once, then re-run this script:"
        echo "   sudo chown -R $CURRENT_USER:$CURRENT_USER $PRODUCTION_DIR/deployment"
        exit 1
    fi
else
    # Check if it's Local Network or Localhost
    if grep -q "127.0.0.1" "$PRODUCTION_DIR/.env" && grep -q "localhost" "$PRODUCTION_DIR/.env"; then
        print_info "Detected: Localhost (Development on a single machine)"
        INSTALL_TYPE="3"
    else
        print_info "Detected: Local Network (LAN access, no domain or SSL)"
        INSTALL_TYPE="2"
    fi
    copy_as_new_if_changed "deployment/docker-compose.production.no-nginx.yml" "$PRODUCTION_DIR/docker-compose.yml" "docker-compose.yml"
fi

apply_required_compose_service_update "celery_download_worker"
apply_required_compose_service_update "celery_copy_worker"
apply_required_compose_service_update "celery_anchor_render_worker"

cp -f deployment/production.Dockerfile "$PRODUCTION_DIR/"
cp -f deployment/entrypoint.production.sh "$PRODUCTION_DIR/"

# Generate docker-compose.override.yml from .env variables
print_info "Generating docker-compose.override.yml from .env..."
if [ -f "$PROJECT_DIR/deployment/scripts/generate-override.sh" ]; then
    cd "$PRODUCTION_DIR"
    if bash "$PROJECT_DIR/deployment/scripts/generate-override.sh"; then
        print_success "docker-compose.override.yml generated successfully"
    else
        print_warning "Failed to generate docker-compose.override.yml (this is optional)"
    fi
    cd "$PROJECT_DIR"
else
    print_warning "generate-override.sh not found - skipping override generation"
fi

# Set ownership of copied files if not root
if [ "$(id -u)" -ne 0 ] && [ -n "${CURRENT_UID:-}" ]; then
    chown "$CURRENT_UID:$CURRENT_GID" "$PRODUCTION_DIR/docker-compose.yml" \
          "$PRODUCTION_DIR/production.Dockerfile" \
          "$PRODUCTION_DIR/entrypoint.production.sh" 2>/dev/null || true
    if [ "$INSTALL_TYPE" = "1" ]; then
        chown "$CURRENT_UID:$CURRENT_GID" "$PRODUCTION_DIR/nginx.conf.template" \
              "$PRODUCTION_DIR/deployment/99-custom-nginx-config.sh" 2>/dev/null || true
    fi
fi

# Copy logo and favicon to project static directory
# Priority: custom files in production > default files in deployment/img
print_info "Copying logo and favicon files..."
mkdir -p "$PROJECT_DIR/ok_tools/static/img"
mkdir -p "$PRODUCTION_DIR/custom/img"

# Check for custom logo in production directory first
if [ -f "$PRODUCTION_DIR/custom/img/logo.png" ]; then
    cp -f "$PRODUCTION_DIR/custom/img/logo.png" "$PROJECT_DIR/ok_tools/static/img/logo.png"
    print_success "Copied custom logo.png from production directory"
elif [ -f "$PRODUCTION_DIR/data/static/img/logo.png" ]; then
    cp -f "$PRODUCTION_DIR/data/static/img/logo.png" "$PROJECT_DIR/ok_tools/static/img/logo.png"
    print_success "Copied logo.png from data/static/img/"
elif [ -f "$PROJECT_DIR/deployment/img/logo.png" ]; then
    cp -f "$PROJECT_DIR/deployment/img/logo.png" "$PROJECT_DIR/ok_tools/static/img/logo.png"
    print_success "Copied default logo.png"
else
    print_warning "logo.png not found - keeping existing file if present"
fi

# Check for custom favicon in production directory first
if [ -f "$PRODUCTION_DIR/custom/img/favicon.ico" ]; then
    cp -f "$PRODUCTION_DIR/custom/img/favicon.ico" "$PROJECT_DIR/ok_tools/static/img/favicon.ico"
    print_success "Copied custom favicon.ico from production directory"
elif [ -f "$PRODUCTION_DIR/data/static/img/favicon.ico" ]; then
    cp -f "$PRODUCTION_DIR/data/static/img/favicon.ico" "$PROJECT_DIR/ok_tools/static/img/favicon.ico"
    print_success "Copied favicon.ico from data/static/img/"
elif [ -f "$PROJECT_DIR/deployment/img/favicon.ico" ]; then
    cp -f "$PROJECT_DIR/deployment/img/favicon.ico" "$PROJECT_DIR/ok_tools/static/img/favicon.ico"
    print_success "Copied default favicon.ico"
else
    print_warning "favicon.ico not found - keeping existing file if present"
fi

# Create configs directory if it doesn't exist and copy config files
# BUT DON'T COPY .env TEMPLATES to avoid overwriting existing .env
mkdir -p "$PRODUCTION_DIR/configs"
# Copy only non-.env template files to avoid overwriting existing .env
find deployment/configs -type f ! -name "*.env.template" -exec cp -f {} "$PRODUCTION_DIR/configs/" \;

# Update .env file with new variables if they don't exist
echo "Checking for missing environment variables..."
ENV_FILE="$PRODUCTION_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    # Backup current .env
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✓ Backed up .env file"
    
    # Function to add variable if not exists
    add_env_var_if_missing() {
        local key="$1"
        local value="$2"
        
        if ! grep -q "^${key}=" "$ENV_FILE"; then
            echo "$key=$value" >> "$ENV_FILE"
            echo "  + Added $key"
        else
            echo "  ✓ $key already exists, keeping current value"
        fi
    }

    # Ensure host/container UID/GID alignment variables exist (used as Docker build args)
    # Default to current host user UID/GID to avoid permission issues with bind mounts (backups/logs/media/static)
    add_env_var_if_missing "USER_UID" "$CURRENT_UID"
    add_env_var_if_missing "USER_GID" "$CURRENT_GID"
    
    # Add new ENV variables with defaults
    add_env_var_if_missing "DJANGO_LOG_LEVEL" "INFO"
    add_env_var_if_missing "DJANGO_LANGUAGE" "de-de"
    add_env_var_if_missing "DJANGO_TIMEZONE" "Europe/Berlin"
    add_env_var_if_missing "DJANGO_STATIC_ROOT" "/app/staticfiles/"
    add_env_var_if_missing "DJANGO_MEDIA_ROOT" "/app/media/"
    add_env_var_if_missing "DJANGO_USE_SECURE_SETTINGS" "True"
    add_env_var_if_missing "MAIL_DEV_SETTINGS" "False"
    add_env_var_if_missing "MEDIA_AUTO_SCAN" "False"
    add_env_var_if_missing "MEDIA_AUTO_COPY_ON_SCHEDULE" "True"
    add_env_var_if_missing "BOOTSTRAP_VERSION" "5.3.3"
    add_env_var_if_missing "BOOTSTRAP_ICONS_VERSION" "1.11.0"
    add_env_var_if_missing "API_PAGE_SIZE" "20"
    add_env_var_if_missing "VIDEO_SCREEN_BOARD_DURATION" "20"
    add_env_var_if_missing "I18N_PHONE_REGION" "DE"
    add_env_var_if_missing "I18N_DATE_FORMAT" "%d.%m.%Y"
    add_env_var_if_missing "CELERY_BROKER_URL" "redis://redis:6379/0"
    add_env_var_if_missing "CELERY_RESULT_BACKEND" "redis://redis:6379/0"
    add_env_var_if_missing "CELERY_DOWNLOAD_WORKER_CONCURRENCY" "1"
    add_env_var_if_missing "CELERY_COPY_WORKER_CONCURRENCY" "1"
    add_env_var_if_missing "CELERY_ANCHOR_RENDER_WORKER_CONCURRENCY" "1"
    add_env_var_if_missing "CELERY_BEAT_EXPIRE_RENTALS" "*/30 * * * *"
    add_env_var_if_missing "CELERY_BEAT_CLEANUP_BACKUPS" "0 2 * * *"
    add_env_var_if_missing "CELERY_BEAT_BACKUP_DB" "0 3 * * *"
    add_env_var_if_missing "CELERY_BEAT_AUTO_SCAN" "0 */2 * * *"
    add_env_var_if_missing "CELERY_BEAT_LINK_LICENSES" "0 4 * * *"
    add_env_var_if_missing "CELERY_BEAT_SYNC_VIDEOS" "0 5 * * *"
    add_env_var_if_missing "CELERY_BEAT_UPDATE_METADATA" "0 1 1 * *"
    add_env_var_if_missing "LOGGING_FILE" "/app/logs/oktools.log"
    
    echo "✓ Environment variables updated"
else
    echo "Warning: .env file not found at $ENV_FILE"
fi

# Check if migration from volumes to bind mounts is needed
print_info "Checking for volume migration..."
MIGRATION_NEEDED=false
cd "$PRODUCTION_DIR"

# Check if old docker-compose.yml uses named volumes
if [ -f "docker-compose.yml" ]; then
    if grep -q "static_volume:\|media_volume:" "docker-compose.yml"; then
        MIGRATION_NEEDED=true
        print_warning "Detected old volume-based configuration - migration required"
    fi
fi

# Migrate from volumes to bind mounts if needed
if [ "$MIGRATION_NEEDED" = true ]; then
    print_header "Migrating from Volumes to Bind Mounts"
    
    # Stop containers first
    print_info "Stopping containers..."
    docker compose down || true
    
    # Create directories
    print_info "Creating bind mount directories..."
    mkdir -p "$PRODUCTION_DIR/data/static" "$PRODUCTION_DIR/data/media" "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups"
    chmod 755 "$PRODUCTION_DIR/data/static" "$PRODUCTION_DIR/data/media"
    chmod 755 "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups"
    
    # Set ownership if not root
    if [ "$(id -u)" -ne 0 ] && [ -n "${CURRENT_UID:-}" ]; then
        chown -R "$CURRENT_UID:$CURRENT_GID" "$PRODUCTION_DIR/data" "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups" 2>/dev/null || true
    fi
    
    # Create temporary container to copy data from volumes
    print_info "Copying data from volumes to bind mounts..."
    
    # Get project name
    PROJECT_NAME=$(grep -m1 "^COMPOSE_PROJECT_NAME=" "$PRODUCTION_DIR/.env" 2>/dev/null | cut -d'=' -f2 || echo "oktools")
    PROJECT_NAME=${PROJECT_NAME:-oktools}
    
    # Copy static files if volume exists
    if docker volume ls | grep -q "${PROJECT_NAME}_static_volume\|static_volume"; then
        VOLUME_NAME=$(docker volume ls | grep -E "${PROJECT_NAME}_static_volume|static_volume" | awk '{print $2}' | head -1)
        if [ -n "$VOLUME_NAME" ]; then
            print_info "  Copying static files from volume: $VOLUME_NAME"
            docker run --rm -v "$VOLUME_NAME:/source:ro" -v "$PRODUCTION_DIR/data/static:/dest" alpine sh -c "cp -a /source/. /dest/ 2>/dev/null || true"
            print_success "  Static files migrated"
        fi
    fi
    
    # Copy media files if volume exists
    if docker volume ls | grep -q "${PROJECT_NAME}_media_volume\|media_volume"; then
        VOLUME_NAME=$(docker volume ls | grep -E "${PROJECT_NAME}_media_volume|media_volume" | awk '{print $2}' | head -1)
        if [ -n "$VOLUME_NAME" ]; then
            print_info "  Copying media files from volume: $VOLUME_NAME"
            docker run --rm -v "$VOLUME_NAME:/source:ro" -v "$PRODUCTION_DIR/data/media:/dest" alpine sh -c "cp -a /source/. /dest/ 2>/dev/null || true"
            print_success "  Media files migrated"
        fi
    fi
    
    # Copy logs if volume exists
    if docker volume ls | grep -q "${PROJECT_NAME}_logs_volume\|logs_volume"; then
        VOLUME_NAME=$(docker volume ls | grep -E "${PROJECT_NAME}_logs_volume|logs_volume" | awk '{print $2}' | head -1)
        if [ -n "$VOLUME_NAME" ]; then
            print_info "  Copying logs from volume: $VOLUME_NAME"
            docker run --rm -v "$VOLUME_NAME:/source:ro" -v "$PRODUCTION_DIR/logs:/dest" alpine sh -c "cp -a /source/. /dest/ 2>/dev/null || true"
            print_success "  Logs migrated"
        fi
    fi
    
    # Copy backups if volume exists
    if docker volume ls | grep -q "${PROJECT_NAME}_backups_volume\|backups_volume"; then
        VOLUME_NAME=$(docker volume ls | grep -E "${PROJECT_NAME}_backups_volume|backups_volume" | awk '{print $2}' | head -1)
        if [ -n "$VOLUME_NAME" ]; then
            print_info "  Copying backups from volume: $VOLUME_NAME"
            docker run --rm -v "$VOLUME_NAME:/source:ro" -v "$PRODUCTION_DIR/backups:/dest" alpine sh -c "cp -a /source/. /dest/ 2>/dev/null || true"
            print_success "  Backups migrated"
        fi
    fi
    
    print_success "Migration completed"
    print_warning "Old volumes will be removed after successful startup"
    print_info "You can manually remove them later with: docker volume prune"
    echo ""
fi

# Ensure all required directories exist with proper permissions
print_info "Ensuring required directories exist..."
mkdir -p "$PRODUCTION_DIR/data/static" "$PRODUCTION_DIR/data/media" "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups"
chmod 755 "$PRODUCTION_DIR/data/static" "$PRODUCTION_DIR/data/media"
chmod 755 "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups"

# Set ownership if not root
if [ "$(id -u)" -ne 0 ] && [ -n "${CURRENT_UID:-}" ]; then
    chown -R "$CURRENT_UID:$CURRENT_GID" "$PRODUCTION_DIR/data" "$PRODUCTION_DIR/logs" "$PRODUCTION_DIR/backups" 2>/dev/null || true
fi

# Check if static directory is empty (bind mount will hide container files if host dir is empty)
if [ -z "$(ls -A "$PRODUCTION_DIR/data/static" 2>/dev/null)" ]; then
    print_warning "Static directory is empty on host"
    print_info "Files will be created after container starts and collectstatic runs"
fi

print_success "Directories checked and permissions set"

# No `docker compose down` here: the old containers keep serving while the
# new images are built and are only replaced by `docker compose up -d` after
# Celery became idle. Only the volume migration above stops the stack.

# Build JSX assets before Docker build
print_info "Building JSX assets..."
NPM_RUNNER="npm"
if command -v npm &> /dev/null && command -v node &> /dev/null; then
    NODE_MAJOR_VERSION=$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo "0")
    if [ "$NODE_MAJOR_VERSION" -ge 18 ] 2>/dev/null; then
        print_info "Using host npm"
    elif command -v docker &> /dev/null; then
        print_warning "Host Node.js is too old for the JSX build — using Dockerized Node.js"
        NODE_IMAGE="node:20-bookworm-slim"
        NPM_RUNNER="docker run --rm -u $(id -u):$(id -g) -v $PROJECT_DIR:/app -w /app -e npm_config_cache=/tmp/.npm $NODE_IMAGE npm"
    else
        print_error "Host Node.js must be version 18 or newer for the JSX build"
        print_info "Upgrade Node.js/npm or install Docker, then re-run update.sh"
        exit 1
    fi
elif command -v docker &> /dev/null; then
    print_warning "npm not found — using Dockerized Node.js for JSX build"
    NODE_IMAGE="node:20-bookworm-slim"
    NPM_RUNNER="docker run --rm -u $(id -u):$(id -g) -v $PROJECT_DIR:/app -w /app -e npm_config_cache=/tmp/.npm $NODE_IMAGE npm"
else
    print_error "npm is not installed and Docker is not available for the Node.js fallback"
    print_info "Install Node.js/npm manually, then re-run update.sh"
    exit 1
fi
cd "$PROJECT_DIR"
if [ ! -d "node_modules" ] || [ "package.json" -nt "node_modules" ]; then
    print_info "Installing Node.js dependencies..."
    if [ -f "package-lock.json" ] || [ -f "npm-shrinkwrap.json" ]; then
        $NPM_RUNNER ci
    else
        print_warning "No package lockfile found — using npm install"
        $NPM_RUNNER install
    fi
fi
$NPM_RUNNER run build:js
print_success "JSX assets built successfully"

cd "$PRODUCTION_DIR"

# Rebuild Docker images while the current containers keep serving.
# Running containers keep their old image; nothing is restarted until
# `docker compose up -d` below.
print_header "Building Docker Images"
if [ "$BUILD_NO_CACHE" != "1" ] && [ "$INTERACTIVE" = "1" ]; then
    print_info "Docker image build options:"
    echo "  1) Build with cache (faster, recommended for regular updates)"
    echo "  2) Build without cache (full rebuild, use when dependencies changed)"
    echo ""
    read -p "Choose build option (1 or 2, default: 1): " -t 10 BUILD_OPTION || BUILD_OPTION=1
    echo ""
    BUILD_OPTION=$(echo "${BUILD_OPTION:-1}" | tr -d '[:space:]' | head -c 1)
    if [ "$BUILD_OPTION" = "2" ]; then
        BUILD_NO_CACHE=1
    fi
fi

if [ "$BUILD_NO_CACHE" = "1" ]; then
    print_info "Building images without cache (full rebuild) - the site stays online meanwhile..."
    BUILD_ARGS=(--no-cache)
else
    print_info "Building images with cache - the site stays online meanwhile..."
    BUILD_ARGS=()
fi
if ! docker compose build "${BUILD_ARGS[@]}"; then
    print_error "Docker build failed - the running containers were not touched"
    exit 1
fi
if [ "$BUILD_NO_CACHE" = "1" ]; then
    print_info "Cleaning up Docker build cache after full rebuild..."
    docker builder prune -f > /dev/null 2>&1 || true
fi
print_success "Docker images built"

# ---------------------------------------------------------------------------
# Wait for idle Celery
# ---------------------------------------------------------------------------
# Restarting a worker in the middle of a task aborts it (2026-11-03: a 6.2 GB
# copy_videos_for_plan run nearly died this way). Wait until no task is running
# and the queues are drained before replacing the containers.

CELERY_IDLE_HELPER="$PROJECT_DIR/deployment/scripts/celery_idle_check.py"
# Long-running queues whose consumers are paused while waiting, so the wait
# ends once the current tasks are done. Queued tasks stay in Redis and run on
# the new workers.
PAUSABLE_QUEUES="copy,download,render,anchor_render"
PAUSED_CONSUMERS_JSON=""
STACK_RESTARTED=0

running_services() {
    docker compose ps --status running --services 2>/dev/null || true
}

running_celery_workers() {
    running_services | grep -E '^celery_' | grep -vx 'celery_beat' || true
}

# Runs celery_idle_check.py inside a running container of the current release.
# Output lines meant for this script start with OKTOOLS_.
celery_helper() {
    local service
    for service in web celery_worker; do
        if running_services | grep -qx "$service"; then
            docker compose exec -T "$service" python - "$@" < "$CELERY_IDLE_HELPER" 2>&1
            return $?
        fi
    done
    echo "no running web or celery_worker container to query Celery from"
    return 1
}

resume_paused_consumers() {
    if [ -z "$PAUSED_CONSUMERS_JSON" ] || [ "$PAUSED_CONSUMERS_JSON" = "{}" ]; then
        PAUSED_CONSUMERS_JSON=""
        return 0
    fi
    local out
    out=$(celery_helper resume "$PAUSED_CONSUMERS_JSON" || true)
    if echo "$out" | grep -q '^OKTOOLS_RESUMED'; then
        print_info "Paused Celery consumers resumed"
        PAUSED_CONSUMERS_JSON=""
    else
        print_warning "Could not resume paused Celery consumers: $PAUSED_CONSUMERS_JSON"
        print_warning "Restart the workers to restore them:"
        echo "   docker compose restart celery_copy_worker celery_download_worker celery_render_worker celery_anchor_render_worker"
    fi
}

# Never leave the old workers paused when the update stops before the restart
# (timeout, build error, Ctrl-C).
on_exit() {
    if [ "$STACK_RESTARTED" != "1" ] && [ -n "$PAUSED_CONSUMERS_JSON" ]; then
        print_info "Restoring paused Celery consumers before exit..."
        resume_paused_consumers
    fi
}
trap on_exit EXIT
trap 'exit 130' INT TERM

wait_for_celery_idle() {
    local expected
    expected=$(running_celery_workers | wc -l | tr -d ' ')
    if [ "$expected" -eq 0 ]; then
        print_info "No Celery workers are running - nothing to wait for"
        return 0
    fi

    print_warning "Please do not start new copy, download or render jobs until the update has finished."
    print_info "Waiting for $expected Celery worker(s) to become idle (timeout ${WAIT_IDLE_TIMEOUT}s, skip with --force)..."

    local paused_queues=""
    if [ "$PAUSE_CONSUMERS" = "1" ]; then
        local paused_out
        paused_out=$(celery_helper pause "$PAUSABLE_QUEUES" || true)
        PAUSED_CONSUMERS_JSON=$(echo "$paused_out" | sed -n 's/^OKTOOLS_PAUSED //p' | tail -1)
        if [ -n "$PAUSED_CONSUMERS_JSON" ]; then
            paused_queues="$PAUSABLE_QUEUES"
            print_info "Paused new tasks on queues: $PAUSABLE_QUEUES"
            print_info "Running tasks continue; queued ones start on the new workers after the update."
        else
            print_warning "Could not pause Celery consumers - waiting without pausing"
            echo "$paused_out" | grep -v '^OKTOOLS_' | tail -3 | sed 's/^/    /' || true
        fi
    fi

    local start elapsed out status_line
    local idle_streak=0
    local last_report=-60
    start=$(date +%s)
    while true; do
        out=$(celery_helper status "$expected" "$paused_queues" || true)
        status_line=$(echo "$out" | grep '^OKTOOLS_STATUS' | tail -1 || true)
        elapsed=$(( $(date +%s) - start ))

        if [[ "$status_line" == *"idle=1"* ]]; then
            idle_streak=$((idle_streak + 1))
            if [ "$idle_streak" -ge 2 ]; then
                print_success "Celery is idle (confirmed twice, waited ${elapsed}s)"
                return 0
            fi
            print_info "Celery looks idle - confirming in 5s..."
        else
            idle_streak=0
            if [ $((elapsed - last_report)) -ge 30 ]; then
                last_report=$elapsed
                print_info "Still waiting for Celery (${elapsed}s of ${WAIT_IDLE_TIMEOUT}s):"
                if [ -n "$status_line" ]; then
                    echo "$out" | sed -n 's/^OKTOOLS_LINE /    /p'
                else
                    print_warning "  Celery state could not be read:"
                    echo "$out" | grep -v '^OKTOOLS_' | tail -3 | sed 's/^/    /' || true
                fi
            fi
        fi

        if [ "$elapsed" -ge "$WAIT_IDLE_TIMEOUT" ]; then
            return 1
        fi
        sleep 5
    done
}

print_header "Waiting for Celery to Become Idle"
if [ "$MIGRATION_NEEDED" = true ]; then
    print_info "Containers were stopped for the volume migration - no Celery tasks to wait for"
elif [ "$FORCE_UPDATE" = "1" ]; then
    print_warning "--force: not waiting for running Celery tasks"
    print_info "Workers still get a warm shutdown (copy/download workers: stop_grace_period)"
elif ! wait_for_celery_idle; then
    print_error "Celery did not become idle within ${WAIT_IDLE_TIMEOUT}s - update aborted"
    print_info "Nothing was restarted: the old containers are still running. The new images are built."
    print_info "Re-run later, raise OKTOOLS_UPDATE_WAIT_IDLE, or use --force to restart anyway."
    exit 1
fi

# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------
print_header "Restarting Containers"
# If docker-compose.yml.new exists, it has NOT been applied (we keep the existing file by design).
# Do NOT remove the .new file; let the operator review/apply it explicitly.
if [ -f "$PRODUCTION_DIR/docker-compose.yml.new" ]; then
    print_warning "docker-compose.yml.new exists (new version saved but not applied)."
    print_warning "Your current deployment is still using the existing docker-compose.yml."
    print_warning "If you want to apply the new compose file automatically, re-run with: FORCE_OVERWRITE=1 ./update.sh"
fi

WORKER_IDS_BEFORE=$(docker compose ps -q 2>/dev/null | sort || true)
UPDATE_FAILED=0
RESTART_STARTED_AT=$(date +%s)
if docker compose up -d; then
    print_success "Containers started with the new images"
else
    print_error "docker compose up -d failed"
    UPDATE_FAILED=1
fi
STACK_RESTARTED=1

# `up -d` only recreates containers whose image or config changed. Workers that
# survived the restart (e.g. nothing new was pulled) are still paused.
if [ -n "$PAUSED_CONSUMERS_JSON" ]; then
    WORKER_IDS_AFTER=$(docker compose ps -q 2>/dev/null | sort || true)
    if [ -n "$(comm -12 <(echo "$WORKER_IDS_BEFORE") <(echo "$WORKER_IDS_AFTER") | grep -v '^$' || true)" ]; then
        resume_paused_consumers
    else
        PAUSED_CONSUMERS_JSON=""
    fi
fi

# The web entrypoint runs migrate, compilemessages, collectstatic,
# migrate_module_configs and the RNN model download on every start. They are
# NOT repeated here: running them twice in parallel raced on 2026-11-02
# (DuplicateColumn and a duplicate austausch.0021 row in django_migrations).
container_state() {
    local cid="$1"
    docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo "missing missing"
}

wait_for_web_healthy() {
    local start elapsed cid state
    local last_report=-60
    start=$(date +%s)
    while true; do
        cid=$(docker compose ps -q web 2>/dev/null | head -1 || true)
        state="missing missing"
        if [ -n "$cid" ]; then
            state=$(container_state "$cid")
        fi
        elapsed=$(( $(date +%s) - start ))
        if [ "$state" = "running healthy" ] || [ "$state" = "running none" ]; then
            return 0
        fi
        if [ $((elapsed - last_report)) -ge 30 ]; then
            last_report=$elapsed
            print_info "  web: $state (${elapsed}s of ${WEB_HEALTH_TIMEOUT}s; migrations run on start)"
        fi
        if [ "$elapsed" -ge "$WEB_HEALTH_TIMEOUT" ]; then
            return 1
        fi
        sleep 5
    done
}

print_info "Waiting for web to become healthy (timeout ${WEB_HEALTH_TIMEOUT}s)..."
if wait_for_web_healthy; then
    print_success "web is healthy (restart took $(( $(date +%s) - RESTART_STARTED_AT ))s)"
else
    print_error "web did not become healthy within ${WEB_HEALTH_TIMEOUT}s"
    print_info "Last 80 lines of the web log:"
    docker compose logs --tail=80 web 2>&1 | sed 's/^/    /' || true
    UPDATE_FAILED=1
fi

# Give the remaining services time to leave the "starting" health state.
print_info "Waiting for the other services to settle..."
SETTLE_START=$(date +%s)
while [ $(( $(date +%s) - SETTLE_START )) -lt 180 ]; do
    STARTING=0
    for cid in $(docker compose ps -q 2>/dev/null || true); do
        case "$(container_state "$cid")" in
            *" starting"|"restarting "*|"created "*) STARTING=1 ;;
        esac
    done
    if [ "$STARTING" = "0" ]; then
        break
    fi
    sleep 5
done

# Static files are collected by the web entrypoint into the bind mount.
if [ -z "$(ls -A "$PRODUCTION_DIR/data/static" 2>/dev/null)" ]; then
    print_warning "No static files in $PRODUCTION_DIR/data/static - check the web log (collectstatic)"
fi

# Cleanup Docker resources
print_info "Cleaning up unused Docker resources..."
docker image prune -f > /dev/null 2>&1 || true
docker volume prune -f > /dev/null 2>&1 || true
print_success "Docker cleanup completed"

# Clean up old volumes after successful update (if migration was performed)
if [ "$MIGRATION_NEEDED" = true ]; then
    echo ""
    print_info "Cleaning up old volumes..."
    # Remove old named volumes (non-destructive - only removes if not in use)
    docker volume ls | grep -E "${PROJECT_NAME}_static_volume|static_volume|${PROJECT_NAME}_media_volume|media_volume|${PROJECT_NAME}_logs_volume|logs_volume|${PROJECT_NAME}_backups_volume|backups_volume" | awk '{print $2}' | while read -r vol; do
        if docker volume inspect "$vol" >/dev/null 2>&1; then
            print_info "  Removing old volume: $vol"
            docker volume rm "$vol" 2>/dev/null || print_info "    (Volume may still be in use, will be cleaned up later)"
        fi
    done || true
    print_success "Volume cleanup completed"
fi

# Run post-update diagnostics. Nothing here may abort the script under set -e:
# the exit code is decided explicitly at the end.
print_header "Running Post-Update Diagnostics"

print_info "1. Container status:"
STACK_HEALTHY=1
SERVICES=$(docker compose config --services 2>/dev/null || true)
if [ -z "$SERVICES" ]; then
    print_error "Could not read the compose services. Is Docker running?"
    STACK_HEALTHY=0
fi
for service in $SERVICES; do
    cid=$(docker compose ps -a -q "$service" 2>/dev/null | head -1 || true)
    if [ -z "$cid" ]; then
        state="missing missing"
    else
        state=$(container_state "$cid")
    fi
    printf "   %-30s %s\n" "$service" "$state"
    case "$state" in
        "running healthy"|"running none") ;;
        *) STACK_HEALTHY=0 ;;
    esac
done
if [ "$STACK_HEALTHY" = "1" ]; then
    print_success "All containers are running and healthy"
else
    print_warning "Some containers are not running or not healthy"
    print_info "Check logs with: docker compose logs -f <service_name>"
    UPDATE_FAILED=1
fi

print_info "2. Checking web service logs for recent errors..."
ERROR_LINES=$(docker compose logs --tail=50 web 2>&1 | grep -iE "(error|exception|traceback)" | grep -vE "(ERROR|WARNING|INFO|DEBUG)\s*\:" | grep -vE "No valid legacy config|Validation|migration|Your models.*have changes" || true)
if [ -n "$ERROR_LINES" ]; then
    print_warning "Potential errors found in web service logs:"
    echo "$ERROR_LINES" | head -5 | sed 's/^/  /'
    print_info "Please review logs above carefully"
else
    print_success "No critical errors found in recent web service logs"
fi

if [ "$UPDATE_FAILED" = "0" ]; then
    print_header "Update Complete!"
else
    print_header "Update Finished With Problems"
fi
echo "Production directory: $PRODUCTION_DIR"
echo ""

# Display access information based on installation type
case $INSTALL_TYPE in
    1)
        # Production with SSL
        DOMAIN_NAME=$(grep "^DOMAIN_NAME=" "$PRODUCTION_DIR/.env" | cut -d'=' -f2 || true)
        print_info "Access admin panel: https://$DOMAIN_NAME/admin"
        ;;
    2)
        # Local Network - detect IP
        LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
        LOCAL_IP=${LOCAL_IP:-127.0.0.1}
        print_info "Access admin panel: http://$LOCAL_IP:8010/admin"
        ;;
    *)
        print_info "Access admin panel: http://localhost:8010/admin"
        ;;
esac

echo ""
print_info "Next steps:"
echo "1. Check container status: cd $PRODUCTION_DIR && docker compose ps"
echo "2. View logs: cd $PRODUCTION_DIR && docker compose logs -f web"
if [ -f "$PRODUCTION_DIR/update.sh" ]; then
    echo "3. For future updates, use: $PRODUCTION_DIR/update.sh [--force] [--no-cache]"
    echo "   (This script automatically updates from git and uses the latest version)"
else
    echo "3. For future updates, use: $SCRIPT_DIR/update.sh [--force] [--no-cache]"
fi
echo "4. If issues occur, check logs or contact support"

if [ "$UPDATE_FAILED" = "0" ]; then
    print_header "Diagnostics Complete"
    exit 0
fi
print_error "Update finished with problems - see the diagnostics above"
exit 1
