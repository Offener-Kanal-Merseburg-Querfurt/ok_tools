from django.contrib.auth import get_user_model
from django.db import transaction


User = get_user_model()


@transaction.atomic
def run():
    """Create an admin."""
    User.objects.create_user(
        email="admin@example.com",
        password="admin",
        is_staff=True,
        is_superuser=True,
    )
