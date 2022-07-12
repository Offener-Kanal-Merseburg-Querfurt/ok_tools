from django.conf import settings


def ok_name(request):
    """Mak OK_NAME available in templates."""
    return {'OK_NAME': settings.OK_NAME}
