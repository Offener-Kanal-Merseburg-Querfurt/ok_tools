========
ok_tools
========

A set of tools to support administrative task in the OKs of the Medienanstalt Sachsen-Anhalt.

**Current Version**: 2.1
**Last Updated**: September 2025

Features
========

**Core Applications:**
- **Contributions Management** - Handle user contributions and submissions
- **Inventory Management** - Track equipment and resources with serial numbers
- **License Management** - Manage broadcasting licenses and youth protection categories
- **Rental System** - Equipment rental management with expiration tracking
- **Planning Tools** - Calendar weeks and scheduling functionality
- **Project Management** - Organize and track various projects
- **User Registration** - User management with notification system
- **Dashboard Analytics** - Comprehensive data visualization and monitoring

**Additional Features:**
- **Accessibility Compliance** - WCAG compliant interface
- **Multi-language Support** - German and English localization
- **Dashboard System** - Comprehensive activity monitoring with interactive charts
- **Admin Interface** - Django admin customization with direct dashboard access
- **REST API** - JSON endpoints for data access
- **Cron Jobs** - Automated rental expiration management
- **Interactive Charts** - Multiple chart types (doughnut, bar, horizontal bar) with data export
- **Real-time Analytics** - User journey tracking and funnel metrics
- **Alert System** - Automated monitoring and threshold-based notifications

Installation
============

**Traditional Installation:**
::

    git clone https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools.git
    cd ok-tools
    python3.10 -m venv .
    bin/pip install -r requirements.txt

**Dependencies:**
- Python 3.10+
- Django 4.2+
- PostgreSQL (production) / SQLite (development)
- Redis (optional, for caching)

Tests
=====

Install the dependencies using requirements-test.txt::

   bin/pip install -r requirements-test.txt

Create static resources::

    OKTOOLS_CONFIG_FILE=test.cfg bin/python manage.py collectstatic

Run the Tests using pytest::

    bin/pytest

**Test Coverage:**
- Unit tests for all applications
- Integration tests for API endpoints
- Coverage reporting with pytest-cov

Configuration
=============

We have provided a minimal config (test.cfg) and an example with
suggested settings for production (production.cfg.example).

**Configuration Files:**
- `test.cfg` - Development and testing configuration
- `production.cfg.example` - Production configuration template
- `gunicorn.conf.py.example` - Gunicorn server configuration

**Environment Variables:**
- `OKTOOLS_CONFIG_FILE` - Path to configuration file
- `DJANGO_SETTINGS_MODULE` - Django settings module
- `DATABASE_URL` - Database connection string

Maintenance/Initial Setup
=========================

Run the typical django scripts after install/update::

    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py migrate
    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py collectstatic
    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py compilemessages

You may want to create a superuser::

    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py createsuperuser

Run Server Locally
==================

To run the server locally you first need to specify a config file. This
configuration is ment for testing only and should not be used in any way for
prouction due to security reasons.
::

    OKTOOLS_CONFIG_FILE=test.cfg bin/python manage.py runserver

Run production server
=====================

We have provided example config for production usage. Copy production.cfg.example and
gunicorn.conf.py.example and edit to your needs.

First you have to install gunicorn::

    bin/pip install gunicorn

Use this command to run the server::

    OKTOOLS_CONFIG_FILE=production.cfg  bin/gunicorn ok_tools.wsgi -c gunicorn.conf.py

**Systemd Services:**
- `scripts/expire-rentals.service` - Rental expiration management
- `scripts/expire-rentals.timer` - Automated rental cleanup

Import legacy data
==================

It is possible to import legacy data from :code:`.xlsx`. Therefore the script
:code:`import_legacy.py` was implemented. To run the script run::

    python manage.py runscript import_legacy

The script takes one workbook with multiple worksheets. The worksheets need to
be named :code:`users`, :code:`contributions`, :code:`categories`, :code:`repetitions` and :code:`projects`.
The path of the imported date can be changed by editing :code:`LEGACY_DATA` in the
:code:`settings.py`. The default path is :code:`../legacy_data/data.xlsx`.

Privacy Policy
==============

To include a privacy policy simply modify :code:`files/privacy_policy.html`.

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

Backup
======

To create backups you can simply copy the .sqlite file::

    cp db.sqlite3 backup.sqlite3

**Automated Backups:**
- Database backup scripts available
- Cron job configuration for regular backups
- Backup rotation and cleanup

Working with translations
=========================

Find new messages like this::

    OKTOOLS_CONFIG_FILE=test.cfg bin/python manage.py makemessages -l de --ignore lib

**Translation Management:**
::

    # Create/update translation files
    bin/python manage.py makemessages -l de -l en

    # Compile translations
    bin/python manage.py compilemessages

    # Collect static files
    bin/python manage.py collectstatic

**Supported Languages:**
- German (de) - Primary language
- English (en) - Secondary language

**Translation Files:**
- `ok_tools/locale/de/LC_MESSAGES/django.po` - German translations
- `ok_tools/locale/en/LC_MESSAGES/django.po` - English translations
- `ok_tools/locale/*/LC_MESSAGES/djangojs.po` - JavaScript translations

Development
===========

**Code Quality:**
- Pre-commit hooks configuration
- isort configuration for import sorting
- Black code formatting
- Flake8 linting

**Testing:**
- pytest configuration
- Coverage reporting
- Test data fixtures

**Static Files:**
- CSS and JavaScript compilation
- Asset optimization
- Responsive design support

**API Documentation:**
- REST API endpoints
- JSON response formats
- Authentication requirements

Deployment
==========

**Environment Setup:**
- Copy configuration examples
- Set environment variables
- Configure database connections
- Set up static file serving

**Monitoring:**
- Application logs
- Error tracking
- Performance monitoring
- Health checks

Support
========

For support and questions:
- GitHub Issues: https://github.com/Offener-Kanal-Merseburg-Querfurt/ok-tools/issues
- Documentation: See inline code comments and docstrings
- Testing: Run test suite for verification

**Contributing:**
- Fork the repository
- Create feature branch
- Submit pull request
- Follow coding standards
