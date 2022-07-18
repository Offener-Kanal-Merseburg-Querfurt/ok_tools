from .models import Profile
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging


logger = logging.getLogger('django')


@receiver(post_save, sender=Profile)
def is_validated(sender, instance, update_fields, **kwargs):
    """If a profile is validated allow its user to log in."""
    if 'verified' in update_fields:
        user = instance.okuser

        profile_ct = ContentType.objects.get_for_model(Profile)
        try:
            login_permission = Permission.objects.get(
                codename='can_login',
                content_type=profile_ct,
            )
        except Permission.DoesNotExist:
            logger.error('Permission "can_login" does not exist.')
            return
        except Permission.MultipleObjectsReturned:
            logger.error('There is more then one Permission "can_login".')
            return

        if instance.verified:
            user.user_permissions.add(login_permission)
        else:
            user.user_permissions.remove(login_permission)

        user.save()
