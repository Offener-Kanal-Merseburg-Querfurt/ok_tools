========
ok_tools
========

A universal set of tools to support administrative tasks for community media organizations. Originally developed for the Offener Kanal system of Medienanstalt Sachsen-Anhalt, now configurable for any organization.

**Current Version**: 4.55.0
**Last Updated**: 21 September 2026

Features
========

**Core Applications:**

- **User Registration** - User management with privacy controls and notification system
  - Email-based authentication (no username required)
  - Profile management with GDPR-compliant data sharing permissions
  - Media authority association for user profiles
  - Print registration form generation
  - Email verification system
  - Member status tracking

- **License Management** - Manage broadcasting licenses with tags and metadata export
  - License creation and confirmation workflow
  - Multi-method digital signatures (draw on page or sign via phone QR)
  - Signature payload v2 support (SVG, biometric points, metadata)
  - Nextcloud video file integration
  - Video upload support
  - Metadata export for planning systems
  - Automated email notification when a published video is available in the Mediathek (with direct link)
  - Periodic Mediathek URL refresh from planning and contribution broadcast data
  - License-to-video file synchronization
  - Tag-based categorization
  - Planning system integration with time extraction

- **Media Files Management** - Advanced video file management with metadata extraction, storage location tracking, and license synchronization
  - Multiple storage location support (Archive, Playout, Custom)
  - Automatic video file scanning and metadata extraction (ffprobe)
  - Video rendering with customizable presets and overlays
  - Async standard video rendering via Celery using a plain 1080p25 / 9000 kbps preset without overlays, intro, or outro
  - Rendered ``_vN`` files are automatically promoted to primary version after successful render; preview renders are excluded
  - Storage location tracking with UNC path support
  - License-to-video file linking and synchronization
  - Checksum calculation (SHA256) for file integrity
  - File operation tracking and logging
  - Automatic orphan license linking
  - Video preset management (database and JSON-based)
  - Background task processing for scanning and metadata updates
  - **Cover / Thumbnail Generation** - Automatically build 16:9 cover images (``{number}_cover.jpg``) from a video frame and license metadata (title, author, category, episode number)
    - Editor-configurable templates (Base, Journal with a large episode number, cinematic Trailer) with per-category accent colors and theme overrides
    - **Cover-Vorlagenregeln** (``CoverTemplate``) - admin rules that pick a template by series (regex on title), category (regex on category name), or a channel-wide default, evaluated by priority
    - **Cover-Grafiken** (``CoverOverlay``) - uploadable PNG/SVG graphic overlays grouped into pools, with configurable text/logo areas and per-overlay toggles (use video frame, darken frame, draw logo, draw title)
    - **Cover-Grafikregeln** (``CoverOverlayRule``) - map a title/category pattern to an overlay pool or explicit graphics, with random (one stable pick per number) or all (variant + contact-sheet selection) modes; graphic rules take precedence over template rules
    - Per-license admin actions to generate/regenerate a cover or produce candidate variants and pick one (frame, timecode, or variant), gated behind the ``cover_enabled`` configuration flag
    - Configurable logo, title/body fonts, category colors, and output storage location in the Media Files Configuration

- **Planning Tools** - Calendar weeks and scheduling functionality with time extraction
  - Daily broadcast plan management (TagesPlan)
  - Calendar week view
  - License integration for broadcast planning
  - Service-layer architecture for planning workflows (plan, validation, notifications, auto-copy)
  - Reusable plan templates and change log tracking for schedule updates
  - Manual and automatic time positioning with overlap protection
  - Multi-day video support with day offset display
  - Draft and planned status tracking
  - Time extraction from license data
  - JSON-based plan storage with comments
  - Optional playout metadata import: sends planned media metadata by filename to an external playout endpoint configured in the Planning Configuration admin UI when a plan is marked planned
  - Optional periodic playout check for files that exist in playout but are still missing metadata
  - Optional playout schedule import and DRF-token-protected playout API endpoints for external playout integrations
  - Optional anchor renderer integration for planned days: waits for playout copy readiness, queues preview rendering asynchronously, exposes task status polling, and names the output file from a configurable pattern
  - Anchor placeholder rules support ``live``, ``title_prefix``, and ``title_contains`` / ``contains`` matching for configurable fallback videos

- **Contributions Management** - Handle user contributions and submissions
  - DISA import from Excel files (XLSX/XLS format support)
  - Primary and repetition contribution detection
  - Broadcast date tracking with live/recorded distinction
  - User contribution listing with statistics (total, live, recorded)
  - Grouped contribution display by license
  - Date extraction from DISA export files (AJAX)
  - Export functionality for contributions
  - Custom date/time range filtering in admin
  - **Program Schedule API** - Token-based API for retrieving program schedules
    - Single date and date range queries (YYYY-MM-DD format)
    - Optional time filtering (start_time, end_time)
    - Automatic info block generation for schedule gaps
    - Consecutive info block merging for optimized schedules

- **Project Management** - Organize and track various projects
  - Project creation with categories and target groups
  - Project leader and media education supervisor assignment
  - Participant tracking and demographics
  - ICS calendar export for project dates
  - Project characteristics analysis (external venue rate, etc.)
  - Date-based project organization

- **Content Exchange (Austausch)** - Exchange content between channels via Nextcloud
  - Nextcloud folder synchronization for content exchange
  - Automatic discovery of exchange items (videos, PDFs, thumbnails)
  - Contribution ID extraction from filenames
  - Exchange feed view for staff members
  - Configurable sync schedule via Celery Beat
  - Support for multiple exchange folders and channels
  - Export to server (``/austausch/feed/``): upload video, PDF, JSON and optional thumbnail to Nextcloud WebDAV via a step-by-step wizard and Celery task
  - Auto-generates a cover thumbnail into the export hand-off directory during export when cover generation is enabled, so exchanged content always ships with a thumbnail
  - Falls back to synchronized JSON metadata when a channel's remote OK-Tools API is unavailable, with retry actions for failed imports
  - Optional module (enabled via AUSTAUSCH_ENABLED setting)

- **Tools Module** - Utility tools for content creation and processing
  - **Video Slideshow Generator**: Create video slideshows from images and videos
    - Drag & drop interface for media upload
    - Audio background music selection
    - Configurable transitions (fade, wipe, slide, etc.)
    - Adjustable duration and quality settings
    - Preview and download capabilities
    - Async generation via Celery
  - **Media Library**: Reusable media files across projects
    - Upload images and videos to shared library
    - Browse library by media type
    - Add library media to any project without re-uploading
    - Staff-only library management
  - Optional module (enabled via TOOLS_ENABLED setting)

- **Inventory Management** - Track equipment and resources with serial numbers
  - Hierarchical location management (Room -> Cabinet structure)
  - Excel import (XLSX) with batch processing
  - Inspection import from CSV/XLSX files
  - Manufacturer, category, and organization tracking
  - Several devices per inventory number, each with its own serial number,
    status, purchase information and inspections
  - Status tracking (in stock, rented, written off, defect, retired)
  - Quantity management with reserved/rented tracking
  - Audit logging for inventory changes
  - Owner-based access control
  - Inventory service interface for rental integration

- **Rental System** - Equipment rental management with expiration tracking
  - Equipment rental requests with status workflow (draft, reserved, issued, returned, cancelled)
  - Room rental support with capacity tracking
  - Configurable working hours for room and equipment bookings, including closed days
  - Equipment sets and templates for predefined configurations
  - Rental transactions (reserve, issue, return, cancel) with audit trail
  - Pick-list printing and per-item checklist notes for issue preparation
  - User access control based on membership status (members can access organization equipment)
  - Availability checking for equipment and rooms
  - Rental item tracking with quantity management
  - Rental issues and problem reporting
  - Equipment condition tracking
  - REST API endpoints for rental operations
  - Calendar view for rental scheduling
  - Week and month calendar views for room booking schedules
  - Past room slots are disabled and visually separated; occupied day-calendar blocks open the corresponding rental detail
  - Period edits reject room or inventory conflicts and atomically synchronize linked room reservations
  - Automatic rental expiration management via cron jobs
  - Configurable automatic return reminder emails for issued rentals, tracked so each rental is reminded once unless delivery fails

- **Dashboard Analytics** - Comprehensive data visualization and monitoring
  - Multiple dashboard widgets (Users, Licenses, Contributions, Projects, Inventory, Notifications, Funnel, Media Data)
  - Interactive charts (doughnut, bar, horizontal bar) with data export
  - User journey tracking through participation funnel
  - Funnel metrics with conversion rate analysis
  - Alert system with configurable thresholds
  - Notification management and statistics
  - Cache invalidation on data changes
  - Statistics service for aggregated data
  - User service for user analytics
  - Notification service for system alerts
  - Real-time dashboard updates
  - Filter system for date ranges and categories
  - Quick stats overview
  - System status monitoring

- **Staff Notification Center** - Interactive daily work surface inside the admin
  - Responsive React event table with rich payload details and a bottom detail drawer
  - Clickable overview cards for live expectations, new events, open actions, postponed items, and problems
  - Personal bulk actions to handle, postpone, reopen, or wake entries, plus explicit permanent suppression
  - Object-specific working links for licenses, rentals, media files, exchange items, and planning dates
  - Live expectations are recomputed from current module data and never persisted as stale events
  - JSX bundle is built automatically by the production update script before ``collectstatic``

- **Background Task Processing** - Asynchronous task execution with Celery for handling time-intensive operations
  - Video file scanning and metadata extraction
  - License-to-video synchronization
  - File operation cleanup
  - Inventory import processing
  - Rental expiration checks
  - Automatic rental return reminders
  - Database backup automation

- **Monitoring & Metrics** - Prometheus integration for application performance monitoring and metrics collection
  - Model operation metrics export
  - Performance tracking
  - Application health monitoring

**Additional Features:**

- **Accessibility Compliance** - WCAG compliant interface

- **Multi-language Support** - German and English localization
  - Translation files (.po) for all user-facing text
  - JavaScript translations (djangojs.po)
  - Automatic translation compilation during deployment

- **Dashboard System** - Comprehensive activity monitoring with interactive charts
  - Main dashboard with overview statistics
  - Specialized widget views for each module
  - Filter system for date ranges and categories
  - Real-time data updates
  - Export functionality for charts and data

- **Admin Interface** - Django admin customization with direct dashboard access
  - Custom admin actions for bulk operations
  - Enhanced filtering and search capabilities
  - Autocomplete fields for related models
  - Export/import functionality (django-import-export)
  - Custom date/time range filters
  - Inline editing for related models

- **REST API** - JSON endpoints for data access with token authentication
  - Rental API endpoints (equipment, rooms, requests, transactions)
  - Dashboard statistics API endpoints
  - Inventory API with user-based filtering
  - Pagination support (default 20 items, configurable up to 200)
  - Search and filtering capabilities
  - Ordering support for list endpoints

- **Token Authentication** - Secure API access with customizable permissions
  - Staff-only token filtering
  - Copy-to-clipboard functionality
  - API documentation modal with code examples
  - Token-based access control

- **PeerTube Integration** - ActivityPub/Fediverse format support for video publishing

- **Custom Widgets** - Enhanced form widgets for improved user experience
  - Tag selection widgets
  - User autocomplete widgets
  - Media data widgets
  - Enhanced form field rendering

- **Data Privacy Controls** - GDPR-compliant data sharing permissions
  - User consent management
  - Selective field exposure in forms
  - Admin-only access to sensitive data

- **Cron Jobs** - Automated rental expiration management
  - Daily rental expiration checks
  - Automated backup creation
  - Cache cleanup tasks
  - File operation cleanup

- **Interactive Charts** - Multiple chart types (doughnut, bar, horizontal bar) with data export
  - Chart.js integration
  - Data export to CSV/Excel
  - Responsive chart rendering
  - Interactive tooltips and legends

- **Real-time Analytics** - User journey tracking and funnel metrics
  - User participation funnel tracking
  - Conversion rate analysis
  - Stage-based journey tracking
  - Funnel breakdown by date ranges

- **Alert System** - Automated monitoring and threshold-based notifications
  - Configurable alert thresholds
  - Multiple metric types (conversion rate, absolute count, trend change)
  - Alert logging and resolution tracking
  - Notification recipients configuration
  - Active/inactive threshold management

- **Video Rendering** - Advanced video rendering with presets and overlays
  - Video preset management (database and JSON-based)
  - Customizable intro/outro overlays
  - Text and image overlay support
  - Animation effects (fade, slide, zoom)
  - Position presets (center, corners, lower third)
  - Template-based rendering
  - Preview functionality for presets

- **Storage Management** - Multiple storage location support
  - Hierarchical storage location tracking
  - UNC path support for Windows networks
  - Automatic file scanning with scheduling
  - Storage type classification (Archive, Playout, Custom)
  - File availability tracking

- **Equipment Sets** - Predefined equipment configurations
  - Equipment set templates
  - Quick rental setup with equipment sets
  - Member-created equipment sets
  - Template-based equipment selection

- **Admin Notifications** - Daily summary and event feed inside the Django admin
  - Summary block on the admin start page: what is expected today and what happened
  - Personal feed with action items that are closed individually
  - Twenty-four event types: rental (hand-out, return, overdue, damage), licenses (confirmation, Nextcloud uploads, approved without a video), media files (new files, format deviating from the encoding preset, missing reel or cover, failed jobs, low disk space), exchange, planning (missing plan, entries without a video, missed broadcasts), registration, tools and system health
  - Filters by module, event type, date range and age, with bulk actions on the selection or on everything matching the filter
  - Three ways to close an entry: personally handled, postponed until tomorrow's summary, or never report this object again
  - Adoption report (page and management command) showing whether the page is read and the items are closed, per event type and per staff member
  - Per-module subscriptions with ready-made presets (Verleih, Redaktion, Technik, Verwaltung)
  - Event types declared in code; the settings page is generated from that registry
  - Every check can be switched off per channel, and a disabled check is not executed at all
  - Visibility mirrors the admin: a subscription never widens access
  - No emails and no polling — the page is the delivery


Installation & Deployment
=========================

OK Tools uses Docker for production deployment. The installation process consists of 5 steps:

**Step 1: Clone the Repository**
::

    git clone https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools.git
    cd ok-tools

**Step 2: Create Your Configuration**

Copy one of the configuration templates from ``deployment/configs/`` and customize it:
::

    cp deployment/configs/okmq.env.template deployment/configs/my-org.env.template
    # Edit deployment/configs/my-org.env.template and replace __REPLACE_ME__ placeholders

Available templates:
- ``okmq.env.template`` - OKMQ configuration template
- ``ok-bayern.env.template`` - Bayern configuration template
- ``ok-nrw.env.template`` - NRW configuration template

**Step 3: Add Logo and Favicon**

Place your organization's branding files in ``deployment/img/``:
::

    cp /path/to/your/logo.png deployment/img/logo.png
    cp /path/to/your/favicon.ico deployment/img/favicon.ico

**Step 4: Run Installation Script**
::

    chmod +x deployment/scripts/install.sh
    ./deployment/scripts/install.sh

The script will guide you through installation type selection (Production, Local Network, or Localhost) and create a production directory at ``../ok_tools_production``.

**Step 5: Update the Application**

After installation, updates are performed from the production directory:
::

    cd ../ok_tools_production
    ./update.sh

The update script automatically pulls the latest code from git, updates Docker containers, runs migrations, and restarts services.

See ``deployment/README.md`` for detailed installation instructions.

**Organization Configuration:**

The installation script will guide you through the configuration process. Configuration templates are located in ``deployment/configs/`` directory.

Key organization settings in the configuration file:
::

    # Organization Configuration
    ORG_NAME=Your Community Media Organization e.V.
    ORG_SHORT_NAME=Your CMO
    ORG_WEBSITE=https://your-organization.com
    ORG_EMAIL=info@your-organization.com
    ORG_ADDRESS=Your Address Here\nCity, Postal Code
    ORG_PHONE=+49 123 456789
    ORG_FAX=+49 123 456790
    ORG_DESCRIPTION=Welcome to our organization! We provide media services...
    ORG_OPENING_HOURS=Mon: 09:00 - 17:00\nTue-Fri: 09:00 - 18:00
    STATE_MEDIA_INSTITUTION=MSA
    ORG_ORGANIZATION_OWNER=Your CMO

**Note:** Use ``\n`` for line breaks in ``ORG_ADDRESS`` and ``ORG_OPENING_HOURS``. Organizations are created automatically on application startup.

**What Gets Created Automatically:**

When you configure ``state_media_institution`` and ``organization_owner``, the system automatically creates:

- **MediaAuthority** object (in ``/admin/registration/mediaauthority/``)
  - Your organization: "OK Bayern" (used for user profile association)
  
- **Organization** objects (in ``/admin/inventory/organization/``)
  - State institution: "BLM" (equipment accessible to all users)
  - Your organization: "OK Bayern" (equipment accessible only to members)

These objects are used for user profiles and equipment ownership/access control throughout the system.

**German State Media Institutions:**

The system supports all German state media institutions:

- **MSA** - Medienanstalt Sachsen-Anhalt
- **LFK** - Landesanstalt für Kommunikation Baden-Württemberg
- **BLM** - Bayerische Landeszentrale für neue Medien
- **mabb** - Medienanstalt Berlin-Brandenburg
- **brema** - Bremische Landesmedienanstalt
- **MA HSH** - Medienanstalt Hamburg / Schleswig-Holstein
- **MMV** - Medienanstalt Mecklenburg-Vorpommern
- **NLM** - Niedersächsische Landesmedienanstalt
- **LfM NRW** - Landesanstalt für Medien NRW
- **LMS** - Landesmedienanstalt Saarland
- **SLM** - Sächsische Landesmedienanstalt
- **TLM** - Thüringer Landesmedienanstalt

See the ``deployment/configs/`` directory for ready-to-use environment file templates for different German states.

**Note:** For Docker deployment, the `.env` file is automatically created in the production directory (``../ok_tools_production/.env``) during installation. The system will use your organization's branding throughout the interface, forms, and communications.

**Dependencies:**
- Docker and Docker Compose
- PostgreSQL (via Docker)
- Redis (via Docker, for caching and Celery)
- Celery and Celery Beat (for background task processing)

All dependencies are automatically installed in Docker containers during deployment. The application uses Python 3.12+ and Django 5.2.7 inside the container.

Production deployments run separate Celery workers for general tasks, video/audio rendering, Nextcloud downloads, video copy jobs, and external anchor rendering. The anchor worker listens on the ``anchor_render`` queue, so programme preview render chains can run on the renderer-side worker instead of occupying local workers.

Tests
=====

Tests can be run inside Docker containers::

    cd ../ok_tools_production
    docker compose exec web python manage.py test

Or using pytest::

    docker compose exec web pytest

**Test Coverage:**
- Unit tests for all applications
- Integration tests for API endpoints with token authentication
- API endpoint tests for license metadata export
- Admin interface tests for custom widgets and forms
- Coverage reporting with pytest-cov

Configuration
=============

Configuration is done via environment variables in `.env` file located in the production directory (``../ok_tools_production/.env``).

**Configuration Files:**
- `.env` file - Environment configuration file (created during installation)
- `deployment/configs/*.env.template` - Environment file templates for different organizations

**Key Configuration Variables:**
- `DJANGO_SECRET_KEY` - Secret key for Django (required)
- `POSTGRES_PASSWORD` - Database password (required)
- `ALLOWED_HOSTS` - Comma-separated list of allowed hosts
- `ORG_NAME`, `ORG_SHORT_NAME` - Organization information
- `ORG_ADDRESS`, `ORG_OPENING_HOURS` - Contact information (use `\n` for line breaks)

See ``deployment/docs/ENV_VARIABLES.md`` for complete reference.

Nextcloud Integration
---------------------

**Nextcloud 32+ Chunked Upload:**

For Nextcloud 32 and later versions, chunked upload is REQUIRED for files larger than 100MB.
The WebDAV API changed in NC32 - the old ``/public.php/webdav/`` endpoint was replaced with ``/public.php/dav/files/{token}/``.

Chunked upload works by:
1. Splitting large files into smaller chunks (default 10MB each)
2. Uploading each chunk separately via WebDAV PUT requests
3. Assembling chunks into the final file using MOVE request

**Configuration:**

- ``NEXTCLOUD_CHUNKED_UPLOAD_ENABLED`` - Enable/disable chunked upload (default: ``true``)
- ``NEXTCLOUD_CHUNKED_UPLOAD_THRESHOLD`` - File size threshold in MB (default: ``100``)
- ``NEXTCLOUD_CHUNK_SIZE`` - Size of each chunk in MB (default: ``10``)

For older Nextcloud versions (<32), you can disable chunked upload or adjust the threshold.

Maintenance
===========

All maintenance tasks are performed inside Docker containers.

**After installation or update:**

The installation and update scripts automatically run::
- Database migrations
- Static files collection
- Translation compilation

**Manual maintenance commands:**

Run migrations::

    cd ../ok_tools_production
    docker compose exec web python manage.py migrate

Collect static files::

    docker compose exec web python manage.py collectstatic --noinput

Compile translations::

    docker compose exec web python manage.py compilemessages

Create superuser::

    docker compose exec web python manage.py createsuperuser

Setup periodic tasks (first time setup)::

    docker compose exec web python manage.py setup_periodic_tasks

**Available Management Commands:**

Media Files::
    - auto_scan - Automated scanning of video storage locations
    - scan_video_storage - Scan video storage and update database
    - update_video_metadata - Update video metadata from files
    - link_orphan_licenses - Link videos for licenses without video files
    - sync_licenses_videos - Sync licenses and videos
    - copy_to_playout - Copy video files to playout storage
    - cleanup_playout - Cleanup playout storage
    - cleanup_missing_files - Cleanup VideoFile records for missing files
    - cleanup_old_file_operations - Cleanup old FileOperation records
    - find_duplicates - Find duplicate video files
    - cleanup_duplicates - Cleanup duplicate video files
    - generate_covers - Generate cover images ({number}_cover.jpg) in bulk (--number/--all/--missing-only/--force/--limit)
    - pick_cover - Promote a reviewed candidate variant to the canonical cover (--number/--variant)

Rental::
    - expire_room_rentals - Expire room rentals and generate transactions
    - fix_quantity_issued - Fix quantity_issued for rental items
    - fix_missing_issue_transactions - Create missing issue transactions
    - test_nextcloud_calendar - Test Nextcloud Calendar integration

Inventory::
    - import_inspections - Import inspections from CSV/XLSX files
    - link_inspections - Deprecated no-op; inspections are linked during import
    - import_locations - Import locations from file

Licenses::
    - import_licenses_from_wp - Import licenses from WordPress SQL dump or CSV
    - delete_imported_licenses - Delete licenses imported from WordPress
    - cleanup_deleted_nextcloud_videos - Cleanup deleted Nextcloud videos

Contributions::
    - export_mediathek_report - Export mediathek import report

Registration::
    - setup_organizations - Create MediaAuthority and Organization objects

Dashboard::
    - check_alerts - Check and trigger alert thresholds

**Note:** Many management commands can be run directly from the admin interface via the System Management page (requires staff access).

**Database backup:**

Create a database backup manually::

    docker compose exec web python manage.py backup_db --compress

Database backups are automatically created daily via Celery Beat (configurable via `CELERY_BEAT_RUN_BACKUP_DB` environment variable). Backups are stored in the configured backup directory (default: `backups/`).

Production Deployment
=====================

OK Tools uses Docker for production deployment.

**Docker Deployment:**

See ``deployment/README.md`` for comprehensive Docker setup instructions.

Quick start::

    git clone https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools.git
    cd ok-tools
    # Copy and customize config template
    cp deployment/configs/okmq.env.template deployment/configs/my-org.env.template
    # Add logo and favicon to deployment/img/
    # Run installation
    chmod +x deployment/scripts/install.sh
    ./deployment/scripts/install.sh
    # For updates
    cd ../ok_tools_production
    ./update.sh

Data Import
============

**Legacy Data Import:**

It is possible to import legacy data from Excel files (:code:`.xlsx`).

The import functionality requires:
- A workbook with worksheets named: :code:`users`, :code:`contributions`, :code:`categories`, :code:`repetitions`, :code:`projects`
- Configure the path in :code:`settings.py` via :code:`LEGACY_DATA` (default: :code:`../legacy_data/data.xlsx`)

**Note:** The legacy import script is a one-time migration tool. If you've already completed your data migration, this feature is not needed for daily operations.

**Contributions Import (DISA):**

Import contributions from DISA export files (Excel format):
- Supports both XLSX and XLS file formats (automatic conversion)
- Date-based filtering (import from specific date onwards)
- Automatic primary/repetition detection
- Batch processing for performance
- AJAX date extraction for user convenience
- Validation of file structure and required worksheets

**Inventory Import:**

Import inventory items from Excel files:
- Excel import (XLSX format) with batch processing (500 items per batch)
- Automatic creation of manufacturers, categories, locations, and organizations
- Inventory number validation (OK-XXXX format)
- Location hierarchy creation (Room -> Cabinet structure)
- Error logging with detailed reports
- Status tracking (pending, processing, completed, failed)

**Inspection Import:**

Import equipment inspection data:
- Supports both CSV and XLSX formats
- Automatic date parsing from various formats
- Links inspections to inventory items by inspection number
- Batch processing for large datasets
- Error handling with detailed logging

Privacy Policy
==============

Privacy policy content is resolved in this order:

1. If ``Organization Configuration -> Privacy Policy (Datenschutz)``
   (``/admin/registration/organizationconfig/1/change/``) is non-empty,
   this value is used.
2. If that field is empty, fallback file :code:`files/privacy_policy.html`
   is used.

The database field supports:

- Placeholder substitution (for example ``{{ OK_NAME }}``, ``{{ OK_ADDRESS }}``)
  using organization context values.
- Basic Markdown-style formatting (headings, lists, emphasis) for plain text
  input.
- Safe HTML rendering with a restrictive allowlist of tags/attributes.

Security
========

Without further actions the view to export the project dates
(:code:`admin/calendar_export`) is reachable without any authentication.

**Security Features:**
- CSRF protection enabled
- XSS protection headers
- SQL injection prevention
- User authentication and authorization
- Role-based access control
- Token-based API authentication with rate limiting
- API throttling (100/hour anonymous, 1000/hour authenticated)
- Comprehensive API access logging with audit trail
- GDPR-compliant data sharing permissions
- Admin-only access controls for sensitive fields
- Enhanced privacy controls for user data

Backup
======

**Automated Backups:**

Database backups are automatically created by the periodic task ``run_backup_db`` (runs daily at 3:00 AM by default). Backups are stored in ``../ok_tools_production/backups/`` directory.

**Manual backup:**

Create a database backup manually using the management command::

    cd ../ok_tools_production
    docker compose exec web python manage.py backup_db --compress

Or using direct pg_dump::

    docker compose exec -T db pg_dump -U oktools oktools > backups/manual-backup-$(date +%Y%m%d-%H%M%S).sql

**Backup management:**
- Automatic backup rotation (keeps last 5 backups)
- Backup cleanup task runs daily via Celery Beat
- Backups include database dump (compressed .sql.gz files)
- Backup directory configurable via `BACKUP_DIR` setting (default: `backups/`)

Working with translations
=========================

**Create/update translation files:**

Translation files are edited in the project directory, then compiled in Docker::

    # In project directory - create/update translation files
    docker compose -f docker-local/docker-compose.yml exec web python manage.py makemessages -l de -l en

    # In production directory - compile translations
    cd ../ok_tools_production
    docker compose exec web python manage.py compilemessages

**Supported Languages:**
- German (de) - Primary language
- English (en) - Secondary language

**Translation Files:**
- `ok_tools/locale/de/LC_MESSAGES/django.po` - German translations
- `ok_tools/locale/en/LC_MESSAGES/django.po` - English translations
- `ok_tools/locale/*/LC_MESSAGES/djangojs.po` - JavaScript translations

**Note:** Translation compilation is automatically performed during installation and updates.

Technical Details
==================

**Code Quality:**
- Pre-commit hooks configuration
- isort configuration for import sorting
- Black code formatting
- Flake8 linting

**Testing:**
- pytest configuration
- Coverage reporting
- Test data fixtures
- Tests run inside Docker containers

**Performance:**
- **Database Query Optimization:**
  - Comprehensive N+1 query elimination across all admin panels
  - Smart use of select_related() and prefetch_related() for FK and M2M relations
  - Optimized API endpoints with 30-70% faster loading times
  - Admin pages reduced queries by 50-90% (e.g., 301 queries → 3 queries)
  - Dashboard widgets optimized with prefetch strategies
- **Indexing Strategy:**
  - Composite indexes on Profile (first_name, last_name)
  - Strategic indexes for filtered fields (status, dates, flags)
- **API Performance:**
  - Rate limiting and throttling (100/hour anonymous, 1000/hour authenticated)
  - Comprehensive logging and monitoring
  - Query optimization reducing data transfer by ~70%
- **Paginator Optimization:**
  - Special handling to preserve prefetch_related() after pagination
  - Prevents query multiplication on paginated endpoints

**Static Files:**
- CSS and JavaScript compilation
- Asset optimization
- Responsive design support

**API Documentation:**
- REST API endpoints with token authentication
- JSON response formats with comprehensive metadata
- Authentication requirements and security
- PeerTube integration with ActivityPub/Fediverse format
- License metadata export with planning system integration
- **Program Schedule API** - Retrieve broadcast schedules with automatic info blocks
- Custom widget development and integration
- Admin interface enhancements and customization

**Service Layer Architecture:**
- Inventory service interface for business logic separation
- Rental service for rental operations
- Statistics service for dashboard data aggregation
- Notification service for alert management
- User service for user analytics
- Service-based architecture for better testability and maintainability

**Caching Strategy:**
- Redis-based caching for dashboard statistics
- Cache invalidation on data changes via signals
- Pattern-based cache key management
- Cache versioning support
- Performance optimization through intelligent caching

**Database Optimization:**
- Batch processing for imports (500 items per batch)
- Optimized contribution primary/repetition detection
- Query optimization with select_related and prefetch_related
- Composite indexes for common query patterns
- Pagination with preserved prefetch relationships

**Admin Interface Enhancements:**
- Custom Token Admin with staff-only filtering
- Enhanced user search with autocomplete functionality
- API documentation modal with code examples
- Copy-to-clipboard functionality for tokens
- Improved form widgets for better user experience
- Custom date/time range filters for contributions
- Export/import functionality for inventory items
- Bulk import actions for DISA files and inventory
- Inline editing for inspections
- Hierarchical location management in admin
- Equipment set management interface
- Rental transaction history view

**Privacy and Security:**
- GDPR-compliant data sharing permissions
- Admin-only access controls for sensitive fields
- Enhanced token authentication system
- Selective field exposure in user forms

Deployment Architecture
=======================

**Infrastructure:**

**Docker Deployment** - Containerized setup with Nginx, PostgreSQL, Redis
- Automated SSL certificate management
- Isolated environment with security hardening
- One-command deployment and updates
- See ``deployment/README.md``

**Deployment Resources:**
- Ready-to-use environment file templates in ``deployment/configs/``
- Comprehensive deployment guides in ``deployment/README.md``
- Nginx configuration with rate limiting and security headers

**Monitoring:**
- Application logs via docker logs
- Error tracking and debugging
- Performance monitoring
- Health check endpoints
- Prometheus metrics export
- Alert logging and resolution tracking
- System status API endpoint
- Dashboard quick stats monitoring

Support
========

For support and questions:
- GitHub Issues: https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools/issues
- Documentation: See inline code comments and docstrings
- Testing: Run test suite for verification
- API Documentation: See README_TOKEN_ADMIN.md for API usage examples
- Admin Interface: See README_PROFILE_UPDATES.md for admin features
- Custom Widgets: See README_TAGS_WIDGET.md for widget development

**Contributing:**
- Fork the repository
- Create feature branch
- Submit pull request
- Follow coding standards
