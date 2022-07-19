from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
import logging


logger = logging.getLogger('django')


class EmailBackend(ModelBackend):
    """Class to authenticate a user by his/her email address as username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Authenticate a user by his/her email address."""
        user_model = get_user_model()
        try:
            user = user_model.objects.get(Q(email__iexact=username))
        except user_model.DoesNotExist:
            # TODO logging messages should be delivered to front end
            logger.error(f'User with E-Mail {username} does not exist.')
            return

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
