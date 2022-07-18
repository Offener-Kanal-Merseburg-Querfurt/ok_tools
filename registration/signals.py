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
    if update_fields and 'verified' in update_fields:
        user = instance.okuser
        login_permission = _get_permission(Profile, 'can_login')

        if instance.verified:
            user.user_permissions.add(login_permission)
        else:
            user.user_permissions.remove(login_permission)


@receiver(post_save, sender=get_user_model())
def is_staff(sender, instance, update_fields, **kwargs):
    """Staff is always allowed to login."""
    login_permission: Permission = None
    if kwargs.get('created') and instance.is_staff:
        login_permission = _get_permission(Profile, 'can_login')
        instance.user_permissions.add(login_permission)

    if update_fields and 'is_staff' in update_fields:
        if not login_permission:
            login_permission = _get_permission(Profile, 'can_login')
        if instance.is_staff:
            instance.user_permissions.add(login_permission)
        else:
            instance.user_permissions.remove(login_permission)


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
    except Permission.MultipleObjectsReturned:
        logger.error(f'There is more then one Permission {codename}.')
        raise

    return permission
