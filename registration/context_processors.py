from django.conf import settings


def ok_name(request):
    """Make OK_NAME available in templates."""
    return {'OK_NAME': settings.OK_NAME}


def ok_name_short(request):
    """Make OK_NAME_SHORT available in templates."""
    return {'OK_NAME_SHORT': settings.OK_NAME_SHORT}
