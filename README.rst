========
ok_tools
========

A set of tools to support administrative task in the OKs of the Medienanstalt Sachsen-Anhalt.

Dependencies
============
::

    pip install -r requirements.txt

Tests
=====

Install the dependencies using requirements-test.txt::

   pip install -r requirements-test.txt

Run the Tests using pytest::

    pytest

Run Server Locally
==================

To run the server locally you first need to specify a config file. This
configuration is ment for testing only and should not be used in any way for
prouction due to security reasons.
::

    OKTOOLS_CONFIG_FILE=test.cfg python manage.py runserver

Language
========

Before using the multi language functionality it is necessary to compile the :code:`.po` files::

    python manage.py compilemessages

Import legacy data
==================

It is possible to import legacy data from :code:`.xlsx`. Therefore the script
:code:`import_legacy.py` was implemented. To run the script run::

    python manage.py runscript import_legacy

The script takes one workbook with multiple worksheets. The worksheets need to
be named :code:`users`, :code:`contributions`, :code:`categories`, :code:`repetitions` and :code:`projects`.
The path of the imported date can be changed by editing :code:`LEGACY_DATA` in the
:code:`settings.py`. The default path is :code:`../legacy_data/data.xlsx`.
