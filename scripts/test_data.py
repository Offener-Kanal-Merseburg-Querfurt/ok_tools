from contributions.models import Contribution
from datetime import date
from datetime import datetime
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from licenses.models import LicenseRequest
from registration.models import Profile


User = get_user_model()


@transaction.atomic
def run():
    """Import test data."""
    # admin
    User.objects.create_user(
        email="admin@example.com",
        password="admin",
        is_staff=True,
        is_superuser=True,
    )

    # testuser 1
    user1 = User.objects.create_user(
        email="maxmustermann@example.com",
        password="userpassword",
    )

    profile1 = Profile.objects.create(
        okuser=user1,
        first_name='Max',
        last_name='Mustermann',
        gender='m',
        birthday=date.fromisoformat('1990-09-01'),
        street='Musterstraße',
        zipcode='06217',
        city='Merseburg',
        verified=True,
    )

    # user 2
    user2 = User.objects.create_user(
        email="monikamustermann@example.com",
        password="userpassword",
    )

    profile2 = Profile.objects.create(
        okuser=user2,
        first_name='Monika',
        last_name='Mustermann',
        gender='w',
        birthday=date.fromisoformat('1995-09-01'),
        street='Musterstraße',
        zipcode='06217',
        city='Merseburg',
        verified=True,
    )

    l1 = LicenseRequest.objects.create(
        profile=profile1,
        title='Title1',
        description='This is the description.',
        duration=timedelta(minutes=30),
        repetitions_allowed=True,
        media_authority_exchange_allowed=False,
        youth_protection_necessary=False,
        store_in_ok_media_library=True,
        confirmed=True,
    )

    LicenseRequest.objects.create(
        profile=profile2,
        title='Title2',
        description='This is the description.',
        duration=timedelta(minutes=30),
        repetitions_allowed=True,
        media_authority_exchange_allowed=False,
        youth_protection_necessary=False,
        store_in_ok_media_library=True,
        confirmed=False,
    )

    l2 = LicenseRequest.objects.create(
        profile=profile2,
        title='Title1',
        description='This is the description.',
        duration=timedelta(minutes=30),
        repetitions_allowed=True,
        media_authority_exchange_allowed=False,
        youth_protection_necessary=False,
        store_in_ok_media_library=True,
        confirmed=True,
    )

    Contribution.objects.create(
        license=l1,
        broadcast_date=datetime(
            year=2022, month=10, day=19, hour=18, minute=30),
        live=False,
    )

    Contribution.objects.create(
        license=l2,
        broadcast_date=datetime(
            year=2022, month=10, day=19, hour=19, minute=30),
        live=False,
    )
