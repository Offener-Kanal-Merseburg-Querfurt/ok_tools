from django.conf import settings
from zoneinfo import ZoneInfo


TZ = ZoneInfo(settings.TIME_ZONE)
