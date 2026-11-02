import json

import pytest

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from rental.views import api_check_room_availability


User = get_user_model()


@pytest.mark.django_db
def test__rental__working_hours__api_check_room_availability_rejects_closed_day_before_room_lookup():
    rf = RequestFactory()
    user = User.objects.create_user(email='member@example.com', password='pwd')
    request = rf.get(
        '/rental/api/check-room-availability',
        data={
            'room_id': 1,
            'start_date': '2026-03-22',
            'start_time': '10:00',
            'end_date': '2026-03-22',
            'end_time': '11:00',
        },
    )
    request.user = user

    response = api_check_room_availability(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['is_available'] is False
    assert payload['message'] == 'The selected start day is closed.'
    assert payload['conflicts'] == []
