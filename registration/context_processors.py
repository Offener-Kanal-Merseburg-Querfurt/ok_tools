from django.conf import settings


def context(request):
    """Make OK_NAME and OK_NAME_SHORT available in templates."""
    return {
        'OK_NAME': settings.OK_NAME,
        'OK_NAME_SHORT': settings.OK_NAME_SHORT
    }
