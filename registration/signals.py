from .models import Profile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging


logger = logging.getLogger('django')


@receiver(post_save, sender=Profile)
def is_validated(sender, instance, update_fields, **kwargs):
    """If a profile is validated allow its user to log in."""
    if ((update_fields and 'verified' in update_fields) or
            kwargs.get('created')):
        user = instance.okuser
        verified_permission = _get_permission(Profile, 'verified')

        if instance.verified:
            user.user_permissions.add(verified_permission)
        else:
            user.user_permissions.remove(verified_permission)


@receiver(post_save, sender=get_user_model())
def is_staff(sender, instance, update_fields, **kwargs):
    """Staff is always allowed to verified."""
    if kwargs.get('created') and instance.is_staff:
        verified_permission = _get_permission(Profile, 'verified')
        instance.user_permissions.add(verified_permission)

    if update_fields and 'is_staff' in update_fields:
        verified_permission = _get_permission(Profile, 'verified')
        if instance.is_staff:
            instance.user_permissions.add(verified_permission)
        else:
            instance.user_permissions.remove(verified_permission)


def _get_permission(model, codename) -> Permission:
    """Return permission for given model if found."""
    ct = ContentType.objects.get_for_model(model)
    try:
        permission = Permission.objects.get(
            codename=codename,
            content_type=ct,
        )
    except Permission.DoesNotExist:
        logger.error(f'Permission {codename} does not exist.')
        raise

    return permission
