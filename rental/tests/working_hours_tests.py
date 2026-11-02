from datetime import datetime
from datetime import time

import pytest

from django.utils import timezone

from rental.models import RentalConfig
from rental.models import RentalRequest
from rental.models import Room
from rental.services.rental_service import RentalService
from rental.working_hours import get_working_hours_by_weekday
from rental.working_hours import validate_working_hours_period
from registration.models import OKUser


@pytest.mark.django_db
def test__rental__working_hours__default_config_serializes_weekdays_and_closed_weekend():
    config = RentalConfig.get_config()

    working_hours = get_working_hours_by_weekday()

    assert working_hours['0']['enabled'] is True
    assert working_hours['0']['start'] == '10:00'
    assert working_hours['0']['end'] == '18:00'
    assert working_hours['5']['enabled'] is False
    assert working_hours['6']['enabled'] is False
    assert config.saturday_start_time is None


@pytest.mark.django_db
def test__rental__working_hours__validation_uses_weekday_specific_hours():
    config = RentalConfig.get_config()
    config.friday_end_time = time(hour=16, minute=0)
    config.save()

    valid_start = timezone.make_aware(datetime(2026, 3, 20, 10, 0))
    valid_end = timezone.make_aware(datetime(2026, 3, 20, 15, 30))
    invalid_end = timezone.make_aware(datetime(2026, 3, 20, 17, 0))

    is_valid, error_message = validate_working_hours_period(valid_start, valid_end)
    assert is_valid is True
    assert error_message is None

    is_valid, error_message = validate_working_hours_period(valid_start, invalid_end)
    assert is_valid is False
    assert error_message == 'The selected end time is outside the configured working hours.'


@pytest.mark.django_db
def test__rental__working_hours__staff_may_book_outside_working_hours():
    member = OKUser.objects.create_user(email='member@example.com', password='testpass123')
    staff = OKUser.objects.create_user(email='staff@example.com', password='testpass123', is_staff=True)
    # Sunday is closed, Friday evening is after closing time.
    sunday_start = timezone.make_aware(datetime(2026, 3, 22, 20, 0))
    sunday_end = timezone.make_aware(datetime(2026, 3, 22, 23, 0))
    evening_start = timezone.make_aware(datetime(2026, 3, 20, 19, 0))
    evening_end = timezone.make_aware(datetime(2026, 3, 20, 22, 0))

    for start, end in ((sunday_start, sunday_end), (evening_start, evening_end)):
        assert validate_working_hours_period(start, end, member)[0] is False
        assert validate_working_hours_period(start, end)[0] is False
        assert validate_working_hours_period(start, end, staff) == (True, None)

    # The period itself still has to make sense.
    assert validate_working_hours_period(sunday_end, sunday_start, staff)[0] is False


@pytest.mark.django_db
def test__rental__working_hours__staff_creates_and_extends_outside_working_hours():
    user = OKUser.objects.create_user(email='user3@example.com', password='testpass123')
    staff = OKUser.objects.create_user(email='staff3@example.com', password='testpass123', is_staff=True)
    room = Room.objects.create(name='Studio C', capacity=8, is_active=True, location='First Floor')

    result = RentalService.create_rental_request(
        {
            'project_name': 'Weekend shoot',
            'purpose': 'Practice',
            'start_date': '2027-03-21T10:00',
            'end_date': '2027-03-21T11:00',
            'action': 'reserved',
            'rooms': [{'room_id': room.id}],
        },
        user,
        staff,
        is_user_request=False,
    )

    assert result['success'] is True, result
    rental_request = RentalRequest.objects.get(id=result['rental_id'])
    assert rental_request.room_rentals.count() == 1
    assert RentalService.extend_rental(
        rental_request,
        timezone.make_aware(datetime(2027, 3, 21, 23, 0)),
        staff,
    ) is True


@pytest.mark.django_db
def test__rental__working_hours__service_rejects_closed_start_day():
    user = OKUser.objects.create_user(email='user@example.com', password='testpass123')
    admin_user = OKUser.objects.create_user(email='admin@example.com', password='testpass123')
    room = Room.objects.create(name='Studio', capacity=8, is_active=True, location='First Floor')

    result = RentalService.create_rental_request(
        {
            'project_name': 'Weekend booking',
            'purpose': 'Practice',
            'start_date': '2027-03-21T10:00',
            'end_date': '2027-03-21T11:00',
            'action': 'reserved',
            'rooms': [{'room_id': room.id}],
        },
        user,
        admin_user,
        is_user_request=False,
    )

    assert result['success'] is False
    assert result['error'] == 'The selected start day is closed.'


@pytest.mark.django_db
def test__rental__working_hours__extend_rental_rejects_end_time_outside_hours():
    user = OKUser.objects.create_user(email='user2@example.com', password='testpass123')
    admin_user = OKUser.objects.create_user(email='admin2@example.com', password='testpass123')
    rental_request = RentalService.create_rental_request(
        {
            'project_name': 'Weekday booking',
            'purpose': 'Practice',
            'start_date': '2027-03-19T10:00',
            'end_date': '2027-03-19T15:00',
            'action': 'reserved',
            'rooms': [{'room_id': Room.objects.create(name='Studio B', capacity=10, is_active=True, location='First Floor').id}],
        },
        user,
        admin_user,
        is_user_request=False,
    )

    created_request = RentalRequest.objects.get(id=rental_request['rental_id'])
    assert RentalService.extend_rental(
        created_request,
        timezone.make_aware(datetime(2027, 3, 19, 19, 0)),
        admin_user,
    ) is False
