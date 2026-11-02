"""Tests for the rental dashboard (RentalListView) filters.

Covers the room/inventory content filter and the user-category filter, whose
categories mirror ``RentalConfig.get_organizations_for``.
"""

from datetime import timedelta
from django.test import RequestFactory
from django.test import TestCase
from django.utils import timezone
from inventory.models import Category
from inventory.models import InventoryItem
from inventory.models import Location
from registration.models import OKUser
from registration.models import Profile
from rental.models import RentalItem
from rental.models import RentalRequest
from rental.models import Room
from rental.models import RoomRental
from rental.views import RentalListView
from urllib.parse import parse_qs
from urllib.parse import urlsplit


class RentalListFilterTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.staff = OKUser.objects.create_user(
            email='staff@example.com', password='pw', is_staff=True)

        self.location = Location.objects.create(name='Room')
        self.category = Category.objects.create(name='Cat')
        self.item = InventoryItem.objects.create(
            inventory_number='OK-F1', quantity=1, status='in_stock',
            location=self.location, category=self.category)
        self.room = Room.objects.create(name='Studio', capacity=4, is_active=True)

    def _user(self, email, *, is_staff=False, member=False, rental_only=False,
              with_profile=True):
        user = OKUser.objects.create_user(email=email, password='pw',
                                          is_staff=is_staff)
        if with_profile:
            Profile.objects.create(okuser=user, first_name='F', last_name='L',
                                   member=member, rental_only=rental_only)
        return user

    def _rental(self, user, *, with_item=False, with_room=False,
                project='P', status='reserved', start=None):
        now = start or timezone.now()
        rr = RentalRequest.objects.create(
            user=user, created_by=self.staff, project_name=project, purpose='x',
            requested_start_date=now, requested_end_date=now + timedelta(days=1),
            status=status)
        if with_item:
            RentalItem.objects.create(
                rental_request=rr, inventory_item=self.item,
                quantity_requested=1)
        if with_room:
            RoomRental.objects.create(
                rental_request=rr, room=self.room, people_count=1,
                requested_start_date=now,
                requested_end_date=now + timedelta(days=1))
        return rr

    def _count(self, **params):
        return self._queryset(**params).count()

    def _queryset(self, **params):
        request = self.factory.get('/rental/admin/', params)
        request.user = self.staff
        view = RentalListView()
        view.request = request
        view.kwargs = {}
        view.args = ()
        return view.get_queryset()

    def test_user_category_filter_partitions_all_rentals(self):
        self._rental(self._user('u@x.com'))                          # user
        self._rental(self._user('m@x.com', member=True))             # member
        self._rental(self._user('r@x.com', rental_only=True))        # rental_only
        self._rental(self._user('e@x.com', is_staff=True))           # employee
        self._rental(self._user('noprof@x.com', with_profile=False))  # user

        self.assertEqual(self._count(), 5)
        self.assertEqual(self._count(user_kind='user'), 2)
        self.assertEqual(self._count(user_kind='member'), 1)
        self.assertEqual(self._count(user_kind='rental_only'), 1)
        self.assertEqual(self._count(user_kind='employee'), 1)
        # The four categories must partition the whole set.
        total = sum(self._count(user_kind=k)
                    for k in ('user', 'member', 'rental_only', 'employee'))
        self.assertEqual(total, self._count())

    def test_content_filter_rooms_vs_inventory(self):
        u = self._user('c@x.com')
        self._rental(u, with_item=True)
        self._rental(u, with_room=True)
        self._rental(u, with_item=True, with_room=True)

        self.assertEqual(self._count(), 3)
        self.assertEqual(self._count(kind='inventory'), 2)
        self.assertEqual(self._count(kind='rooms'), 2)

    def test_filters_combine(self):
        self._rental(self._user('a@x.com', member=True), with_room=True)
        self._rental(self._user('b@x.com', is_staff=True), with_room=True)
        self._rental(self._user('c@x.com', member=True), with_item=True)

        self.assertEqual(self._count(user_kind='member', kind='rooms'), 1)

    def test_no_duplicate_rows_with_multiple_items(self):
        item2 = InventoryItem.objects.create(
            inventory_number='OK-F2', quantity=1, status='in_stock',
            location=self.location, category=self.category)
        rr = self._rental(self._user('d@x.com'), with_item=True)
        RentalItem.objects.create(
            rental_request=rr, inventory_item=item2, quantity_requested=1)
        # Two items on one rental must still count the rental once.
        self.assertEqual(self._count(kind='inventory'), 1)

    def test_project_sorting_works_for_every_stored_status(self):
        """The same allowlisted ordering applies before any status tab."""
        for status in ('draft', 'reserved', 'issued', 'returned', 'cancelled'):
            alpha = self._rental(
                self._user(f'{status}-a@x.com'), project='Alpha',
                status=status)
            zulu = self._rental(
                self._user(f'{status}-z@x.com'), project='Zulu',
                status=status)

            ascending = list(self._queryset(
                status=status, sort='project', direction='asc').values_list(
                    'pk', flat=True))
            descending = list(self._queryset(
                status=status, sort='project', direction='desc').values_list(
                    'pk', flat=True))

            self.assertEqual(ascending, [alpha.pk, zulu.pk])
            self.assertEqual(descending, [zulu.pk, alpha.pk])

    def test_overdue_tab_can_be_sorted_by_time(self):
        """The derived overdue filter uses the same time header ordering."""
        now = timezone.now()
        earlier = self._rental(
            self._user('early@x.com'), status='issued',
            start=now - timedelta(days=5))
        later = self._rental(
            self._user('late@x.com'), status='issued',
            start=now - timedelta(days=3))

        result = list(self._queryset(
            status='overdue', sort='time', direction='asc').values_list(
                'pk', flat=True))

        self.assertEqual(result, [earlier.pk, later.pk])

    def test_items_sort_counts_inventory_and_rooms(self):
        """The Items header orders by all content displayed in that column."""
        user = self._user('content@x.com')
        empty = self._rental(user, project='Empty')
        inventory = self._rental(user, with_item=True, project='Inventory')
        mixed = self._rental(
            user, with_item=True, with_room=True, project='Mixed')

        result = list(self._queryset(
            sort='items', direction='desc').values_list('pk', flat=True))

        self.assertEqual(result, [mixed.pk, inventory.pk, empty.pk])

    def test_invalid_sort_parameters_fall_back_to_latest_first(self):
        """Arbitrary query values never become database ordering clauses."""
        user = self._user('safe@x.com')
        older = self._rental(user, project='Older')
        newer = self._rental(user, project='Newer')
        RentalRequest.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=1))

        result = list(self._queryset(
            sort='__unsafe', direction='sideways').values_list(
                'pk', flat=True))

        self.assertEqual(result, [newer.pk, older.pk])

    def test_sort_links_preserve_filters_in_rendered_page(self):
        """Header clicks and pagination keep the active list controls."""
        self.client.force_login(self.staff)

        response = self.client.get('/rental/admin/', {
            'status': 'reserved',
            'user_kind': 'member',
            'kind': 'rooms',
            'sort': 'time',
            'direction': 'asc',
        })

        self.assertEqual(response.status_code, 200)
        headers = response.context['sort_headers']
        self.assertEqual(
            [header['key'] for header in headers],
            ['id', 'project', 'time', 'status', 'items'],
        )
        project_query = parse_qs(urlsplit(headers[1]['url']).query)
        self.assertEqual(project_query, {
            'status': ['reserved'],
            'user_kind': ['member'],
            'kind': ['rooms'],
            'sort': ['project'],
            'direction': ['asc'],
        })
        time_header = headers[2]
        self.assertTrue(time_header['active'])
        self.assertEqual(time_header['aria_sort'], 'ascending')
        self.assertEqual(
            parse_qs(urlsplit(time_header['url']).query)['direction'],
            ['desc'],
        )
        self.assertEqual(parse_qs(response.context['pagination_query']), {
            'status': ['reserved'],
            'user_kind': ['member'],
            'kind': ['rooms'],
            'sort': ['time'],
            'direction': ['asc'],
        })

    def test_search_by_profile_name_email_and_id(self):
        anna = self._user('anna@x.com')
        anna.profile.first_name = 'Anna'
        anna.profile.last_name = 'Schmidt'
        anna.profile.save()
        anna_rental = self._rental(anna, project='Doku')
        other = self._rental(self._user('bob@x.com'), project='Film')

        def found(q):
            return set(self._queryset(q=q).values_list('pk', flat=True))

        self.assertEqual(found('Anna'), {anna_rental.pk})
        self.assertEqual(found('schmi'), {anna_rental.pk})
        self.assertEqual(found('Anna Schmidt'), {anna_rental.pk})
        self.assertEqual(found('Anna Film'), set())
        self.assertEqual(found('bob@'), {other.pk})
        self.assertEqual(found(str(other.pk)), {other.pk})
        self.assertEqual(found(f'#{anna_rental.pk}'), {anna_rental.pk})
