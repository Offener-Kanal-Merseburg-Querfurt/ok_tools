"""
Django settings for ok_tools project.

Generated by 'django-admin startproject' using Django 4.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""

from pathlib import Path
import configparser
import os



# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# parse configurations, set by component
config = configparser.RawConfigParser()
if 'OKTOOLS_CONFIG_FILE' in os.environ:
    config.read_file(open(
        os.environ.get('OKTOOLS_CONFIG_FILE'), encoding='utf-8'
    ))
else:
    raise ValueError('No configuration file found for ok_tools')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config.get('django', 'secret_key', fallback=None)


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config.getboolean('django', 'debug', fallback=False)

hosts = config.get('django', 'allowed_hosts', fallback=None)
ALLOWED_HOSTS = hosts.split() if hosts else []

# Loglevel
DJANGO_LOG_LEVEL = os.getenv('DJANGO_LOG_LEVEL', 'INFO')

# Application definition

INSTALLED_APPS = [
    'registration.apps.RegistrationConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ok_tools.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ok_tools.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# CSRF settings
CSRF_TRUSTED_ORIGINS = ['https://okmq.gocept.fcio.net', 'https://localhost']

SESSION_COOKIE_SECURE = True

CSRF_COOKIE_SECURE = True

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CORS_ORIGIN_WHITELIST = ['https://okmq.gocept.fcio.net/']

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = config.get('django', 'language', fallback='de-de')

TIME_ZONE = config.get('django', 'timezone', fallback='Europe/Berlin')

USE_I18N = True

USE_TZ = True

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

STATICFILES_DIR = [
    os.path.join(BASE_DIR, 'static'),
]
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_ROOT = config.get('django', 'static')
STATIC_URL = 'static/'

# ManifestStaticFilesStorage is recommended in production, to prevent outdatedhttp://localhost:8000/
# JavaScript / CSS assets being served from cache (e.g. after a Wagtail upgrade).
# See https://docs.djangoproject.com/en/3.1/ref/contrib/staticfiles/#manifeststaticfilesstorage
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# authenticatable users
AUTH_USER_MODEL = 'registration.Client'
AUTHENTICATION_BACKENDS = ['registration.backends.EmailBackend']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': DJANGO_LOG_LEVEL,
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'ok_tools-debug.log'),
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': DJANGO_LOG_LEVEL,
        },
    },
}
