from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
import logging


class EmailBackend(ModelBackend):
    """Class to authenticate a user by his/her email address."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        """Authenticate a user by his/her email address."""
        user_model = get_user_model()
        try:
            user = user_model.objects.get(Q(email__iexact=email))
        except user_model.DoesNotExist:
            # TODO logging messages should be deliverd to front end
            logging.error(f'User with E-Mail {email} does not exist.')
        except user_model.MutlipleObjectsReturned:
            logging.error(
                f'There are more then one user with the E-Mail {email}.')

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
