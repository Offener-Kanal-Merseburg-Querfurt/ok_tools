from django.conf import settings


def ok_name(request):
    """Make OK_NAME available in templates."""
    return {'OK_NAME': settings.OK_NAME}
