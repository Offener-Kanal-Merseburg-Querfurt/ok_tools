"""Tests for the dashboard inventory endpoint ``api_user_inventory_simple``."""

from django.test import RequestFactory
from django.test import TestCase
from inventory.models import Category
from inventory.models import InventoryItem
from inventory.models import Location
from registration.models import OKUser
from rental.views import api_get_user_inventory_simple
import json


class InventorySimpleProfileTests(TestCase):
    """A missing profile must only block non-staff accounts."""

    def setUp(self):
        self.factory = RequestFactory()
        InventoryItem.objects.create(
            inventory_number='OK-S1', quantity=1, status='in_stock',
            available_for_rent=True,
            location=Location.objects.create(name='Room'),
            category=Category.objects.create(name='Cat'))

    def _get(self, user):
        request = self.factory.get('/')
        request.user = user
        return api_get_user_inventory_simple(request, user.id)

    def test_staff_without_profile_gets_inventory(self):
        staff = OKUser.objects.create_user(
            email='staff-no-profile@example.com', password='pw', is_staff=True)

        response = self._get(staff)

        self.assertEqual(response.status_code, 200)
        numbers = [i['inventory_number'] for i in json.loads(response.content)['inventory']]
        self.assertIn('OK-S1', numbers)

    def test_user_without_profile_is_rejected(self):
        user = OKUser.objects.create_user(
            email='user-no-profile@example.com', password='pw')

        response = self._get(user)

        self.assertEqual(response.status_code, 400)
