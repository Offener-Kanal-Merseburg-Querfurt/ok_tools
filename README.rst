========
ok_tools
========

A set of tools to support administrative task in the OKs of the Medienanstalt Sachsen-Anhalt.

Installation
============
::

    git clone https://github.com/gocept/ok-tools.git
    cd ok-tools
    python3.10 -m venv .
    bin/pip install -r requirements.txt

Tests
=====

Install the dependencies using requirements-test.txt::

   bin/pip install -r requirements-test.txt

Run the Tests using pytest::

    bin/pytest


Configuration
=============

We have provided a minimal config (test.cfg) and an example with
suggested settings for production (production.cfg.example).


Run Server Locally
==================

To run the server locally you first need to specify a config file. This
configuration is ment for testing only and should not be used in any way for
prouction due to security reasons.
::

    OKTOOLS_CONFIG_FILE=test.cfg bin/python manage.py runserver


Maintenance/Initial Setup
=========================

Run the typical django scripts after install/update::

    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py migrate
    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py collectstatic
    OKTOOLS_CONFIG_FILE=yourconfig.cfg bin/python manage.py compilemessages


Run production server
=====================

We have provided example config for production usage. Copy production.cfg.example and
gunicorn.conf.py.example and edit to your needs.

First you have to install gunicorn::

    bin/pip install gunicorn

Use this command to run the server::

    OKTOOLS_CONFIG_FILE=production.cfg  bin/gunicorn ok_tools.wsgi -c gunicorn.conf.py



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
(:conde:`admin/calendar_export`) is reachable without any authentication.
