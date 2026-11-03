# OK Tools Installation Guide

This guide describes the installation and update process for OK Tools using Docker containers.

## Installation Process

### Step 1: Clone the Repository

Clone the repository from GitHub:

```bash
git clone https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools.git
cd ok-tools
```

### Step 2: Create Your Configuration

Copy one of the configuration templates from `deployment/configs/` and customize it:

```bash
cp deployment/configs/okmq.env.template deployment/configs/my-org.env.template
# Edit deployment/configs/my-org.env.template and replace __REPLACE_ME__ placeholders
```

Available templates:
- `okmq.env.template` - OKMQ configuration template
- `ok-bayern.env.template` - Bayern configuration template
- `ok-nrw.env.template` - NRW configuration template

**Note:** The installation script will use templates from `deployment/configs/` during interactive setup. You can also edit templates directly before running the installation script.

### Step 3: Add Logo and Favicon

Place your organization's branding files in `deployment/img/`:

```bash
cp /path/to/your/logo.png deployment/img/logo.png
cp /path/to/your/favicon.ico deployment/img/favicon.ico
```

These files will be automatically copied to `ok_tools/static/img/` during installation.

### Step 4: Run Installation Script

Run the installation script:

```bash
chmod +x deployment/scripts/install.sh
./deployment/scripts/install.sh
```

The script will:
- Guide you through installation type selection (Production, Local Network, or Localhost)
- Prompt for configuration values or use a template
- Create production directory at `../ok_tools_production`
- Generate `.env` file with your settings
- Copy necessary Docker files
- Start Docker containers
- Run database migrations
- Collect static files

### Step 5: Update the Application

After installation, updates are performed from the production directory:

```bash
cd ../ok_tools_production
./update.sh
```

The update script will:
- Back up `.env` and the database (`pg_dump` from the running `db` container)
- Pull latest code from git repository and build the JSX assets
- Build the new Docker images while the running containers keep serving
- Wait until Celery is idle (no running task, empty queues); the copy/download/render queues are paused meanwhile
- Restart the containers (`docker compose up -d`); the web container runs migrations, `compilemessages` and `collectstatic` on start
- Wait for `web` to become healthy and exit non-zero if any container is not healthy

Options and settings:

```bash
./update.sh --force      # restart without waiting for running Celery tasks
./update.sh --no-cache   # clean image build
./update.sh --no-pause   # wait without pausing the copy/download/render queues
OKTOOLS_UPDATE_WAIT_IDLE=7200 ./update.sh   # max wait for idle Celery (default 3600 s)
```

On timeout the update aborts and the old containers keep running. Without a terminal (ssh without `-t`, cron) the script asks no questions and builds with cache.

**Note:** The `update.sh` script is automatically created in the production directory during installation.

## Installation Types

The installation script offers three installation types:

- **Production**: Public server with domain name, Nginx web server, and SSL certificates
- **Local Network**: LAN access without domain or SSL (for internal networks)
- **Localhost**: Development on a single machine

## Configuration

### Environment Variables

The configuration system uses environment variables organized into logical groups:

#### Core Django Settings
- `DJANGO_SECRET_KEY` - Secret key for Django (required)
- `DEBUG` - Enable/disable debug mode
- `ALLOWED_HOSTS` - Comma-separated list of allowed hosts
- `DJANGO_LOG_LEVEL` - Logging level (INFO, DEBUG, etc.)

#### Database Configuration
- `POSTGRES_DB` - Database name
- `POSTGRES_USER` - Database user
- `POSTGRES_PASSWORD` - Database password (required)
- `DATABASE_URL` - Full database connection string

#### Organization Settings
- `ORG_NAME` - Organization full name
- `ORG_SHORT_NAME` - Organization short name
- `ORG_WEBSITE` - Organization website
- `ORG_EMAIL` - Organization email
- `ORG_PHONE` - Organization phone
- `ORG_ADDRESS` - Organization address (use `\n` for line breaks)
- `ORG_OPENING_HOURS` - Opening hours (use `\n` for line breaks)

#### Celery Configuration
- `CELERY_BROKER_URL` - Redis broker URL
- `CELERY_RESULT_BACKEND` - Result backend (django-db or redis)
- `CELERY_BEAT_*` - Scheduled task configurations

**For complete reference:** See [Environment Variables Reference](docs/ENV_VARIABLES.md)

## Next Steps

After installation, you should:

1. **Check container status:**
   ```bash
   cd ../ok_tools_production
   docker compose ps
   ```

2. **View application logs:**
   ```bash
   cd ../ok_tools_production
   docker compose logs -f web
   ```

3. **Access the admin panel:**
   - Production with SSL: `https://your-domain.com/admin`
   - Production without SSL: `http://your-domain.com/admin`
   - Local Network: `http://server-ip:8010/admin`
   - Localhost: `http://localhost:8010/admin`
   
   Use the superuser credentials you configured during installation.

4. **Update the application:**
   ```bash
   cd ../ok_tools_production
   ./update.sh
   ```

## Testing Configuration

### Validate .env File
```bash
cd ../ok_tools_production
docker compose --env-file .env config
```

### Run Django Checks
```bash
cd ../ok_tools_production
docker compose exec web python manage.py check --deploy
```

### Run Integration Tests
```bash
./deployment/tests/test_env_config.sh
```

## Troubleshooting

### Common Issues

1. **Permission denied on .env file:**
   ```bash
   chmod 600 ../ok_tools_production/.env
   ```

2. **Configuration not loading:**
   - Verify .env file is in the correct location (`../ok_tools_production/.env`)
   - Check variable names match exactly
   - Ensure no syntax errors in .env file

3. **Database connection issues:**
   - Verify database container is running: `docker compose ps`
   - Check DATABASE_URL in .env file
   - Ensure network connectivity between containers

4. **Update script not found:**
   - The update script is created automatically during installation
   - If missing, you can run updates from the project directory:
     ```bash
     cd ok-tools
     ./deployment/scripts/update.sh
     ```

### Getting Help

1. Check container status: `docker compose ps`
2. Review logs: `docker compose logs -f web`
3. Verify configuration in the generated `.env` file
4. Ensure all required ports are available
5. Run integration tests: `./deployment/tests/test_env_config.sh`
6. Create an issue: https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools/issues

## Documentation

- [Environment Variables Reference](docs/ENV_VARIABLES.md) - Complete reference for all environment variables
- [Environment Template](docs/ENV_TEMPLATE.md) - Template with detailed variable descriptions
- [Periodic Tasks Guide](docs/PERIODIC_TASKS.md) - How to manage Celery Beat periodic tasks
- [Volume Mounts Guide](docs/VOLUME_MOUNTS.md) - How to configure NAS and custom volume mounts

## Support

If you encounter problems during installation:

1. Check container status: `docker compose ps`
2. Review logs: `docker compose logs -f web`
3. Verify configuration in the generated `.env` file
4. Ensure all required ports are available
5. Run integration tests: `./deployment/tests/test_env_config.sh`
6. Create an issue: https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools/issues
