"""Tests for consumables handed out with a rental but not kept in inventory."""

from datetime import timedelta
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rental.models import RentalConfig
from rental.models import RentalConsumable
from rental.models import RentalItem
from rental.models import RentalRequest
from rental.services.consumables import parse_consumable_lines
from rental.views import serialize_user
from unittest.mock import patch
import json
import pytest


def _users(django_user_model):
    borrower = django_user_model.objects.create_user(email='borrower@example.com', password='pwd')
    staff = django_user_model.objects.create_user(
        email='staff@example.com', password='pwd', is_staff=True)
    return borrower, staff


def _rental(borrower, staff, status='issued', project='Shoot'):
    now = timezone.now()
    return RentalRequest.objects.create(
        user=borrower,
        created_by=staff,
        project_name=project,
        purpose='Testing consumables',
        requested_start_date=now - timedelta(hours=2),
        requested_end_date=now + timedelta(hours=2),
        status=status,
        rental_type='equipment',
    )


def _issued_item(rental):
    from inventory.models import InventoryItem
    from inventory.models import Location
    from inventory.models import Organization

    item = InventoryItem.objects.create(
        inventory_number=f'OK-CONS-{rental.pk}',
        description='Camera',
        quantity=1,
        status='in_stock',
        available_for_rent=True,
        owner=Organization.objects.create(name=f'Org {rental.pk}'),
        location=Location.objects.create(name=f'Shelf {rental.pk}'),
    )
    return RentalItem.objects.create(
        rental_request=rental,
        inventory_item=item,
        quantity_requested=1,
        quantity_issued=1,
    )


def test__rental__consumables__parse_lines():
    assert parse_consumable_lines(
        'кабель xlr 5м - 3\n'
        'кабель xlr 3m - 1\n'
        'sdcard 64Gb 5\n'
        'XLR 5m\n'
        '\n'
        '- Gaffer x2\n'
        'Batterien AA: 8 Stk\n'
        '12\n'
    ) == [
        ('кабель xlr 5м', 3),
        ('кабель xlr 3m', 1),
        ('sdcard 64Gb', 5),
        ('XLR 5m', 1),
        ('Gaffer', 2),
        ('Batterien AA', 8),
        ('12', 1),
    ]


def _post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type='application/json')


@pytest.mark.django_db
def test__rental__consumables__checklist_add_edit_tick_remove(client, django_user_model):
    borrower, staff = _users(django_user_model)
    rental = _rental(borrower, staff)
    client.force_login(staff)

    response = _post_json(client, reverse('rental:add_consumables', args=[rental.pk]),
                          {'lines': 'Xlr Kabel 3m - 3\nAkkus 3\nTasche 1'})

    assert response.status_code == 200
    assert [(i['name'], i['quantity']) for i in response.json()['items']] == [
        ('Xlr Kabel 3m', 3), ('Akkus', 3), ('Tasche', 1)]
    detail = client.get(reverse('rental:rental_detail', args=[rental.pk]))
    assert detail.status_code == 200
    assert [i['name'] for i in detail.context['consumables_json']] == ['Xlr Kabel 3m', 'Akkus', 'Tasche']

    cable, batteries, bag = rental.consumables.all()
    update = 'rental:update_consumable'
    edited = _post_json(client, reverse(update, args=[rental.pk, batteries.pk]), {'line': 'Akkus NP-F 4'})
    assert (edited.json()['item']['name'], edited.json()['item']['quantity']) == ('Akkus NP-F', 4)

    ticked = _post_json(client, reverse(update, args=[rental.pk, cable.pk]), {'checked': True})
    assert ticked.json()['item']['status'] == 'returned'
    # A ticked line is history: it can be unticked, not edited or removed.
    assert _post_json(client, reverse(update, args=[rental.pk, cable.pk]), {'line': 'x'}).status_code == 400
    assert _post_json(client, reverse('rental:delete_consumable', args=[rental.pk, cable.pk]), {}).status_code == 400
    unticked = _post_json(client, reverse(update, args=[rental.pk, cable.pk]), {'checked': False})
    assert unticked.json()['item']['status'] == 'out'

    assert _post_json(client, reverse('rental:delete_consumable', args=[rental.pk, bag.pk]), {}).status_code == 200
    assert list(rental.consumables.values_list('name', flat=True)) == ['Xlr Kabel 3m', 'Akkus NP-F']


@pytest.mark.django_db
def test__rental__consumables__tick_after_return(client, django_user_model):
    borrower, staff = _users(django_user_model)
    rental = _rental(borrower, staff, status='closed')
    missing = RentalConsumable.objects.create(
        rental_request=rental, name='XLR', quantity=2, quantity_returned=1,
        status=RentalConsumable.STATUS_MISSING, returned_at=timezone.now())
    returned = RentalConsumable.objects.create(
        rental_request=rental, name='Card', quantity=1, quantity_returned=1,
        status=RentalConsumable.STATUS_RETURNED, returned_at=timezone.now())
    client.force_login(staff)
    update = 'rental:update_consumable'

    assert _post_json(client, reverse('rental:add_consumables', args=[rental.pk]),
                      {'lines': 'Late - 1'}).status_code == 400
    _post_json(client, reverse(update, args=[rental.pk, missing.pk]), {'checked': True})
    # Unticking after the return makes it missing, so it is reminded about.
    _post_json(client, reverse(update, args=[rental.pk, returned.pk]), {'checked': False})

    missing.refresh_from_db()
    returned.refresh_from_db()
    assert (missing.status, missing.quantity_returned, missing.resolved_by) == ('returned', 2, staff)
    assert (returned.status, returned.quantity_returned) == ('missing', 0)

    written_off = _post_json(client, reverse(update, args=[rental.pk, returned.pk]), {'write_off': True})
    assert written_off.json()['item']['status'] == 'written_off'
    assert _post_json(client, reverse(update, args=[rental.pk, returned.pk]),
                      {'checked': True}).status_code == 400


@pytest.mark.django_db
def test__rental__consumables__member_cannot_add(client, django_user_model):
    borrower, staff = _users(django_user_model)
    rental = _rental(borrower, staff)
    client.force_login(borrower)

    _post_json(client, reverse('rental:add_consumables', args=[rental.pk]), {'lines': 'XLR - 2'})

    assert not rental.consumables.exists()


@pytest.mark.django_db
def test__rental__consumables__return_keeps_missing_and_closes_rental(client, django_user_model):
    borrower, staff = _users(django_user_model)
    rental = _rental(borrower, staff)
    rental_item = _issued_item(rental)
    cables = RentalConsumable.objects.create(rental_request=rental, name='XLR 5m', quantity=3)
    card = RentalConsumable.objects.create(rental_request=rental, name='SD 64GB', quantity=1)
    tape = RentalConsumable.objects.create(rental_request=rental, name='Gaffer', quantity=1)
    client.force_login(staff)

    return_page = client.get(reverse('rental:rental_return', args=[rental.pk]))
    assert [c['name'] for c in return_page.context['consumables_json']] == [
        'XLR 5m', 'SD 64GB', 'Gaffer']

    with patch('rental.views.send_return_receipt_email') as mocked_receipt:
        response = client.post(
            reverse('rental:api_return_rental_items'),
            data=json.dumps({
                'rental_id': rental.pk,
                'items': [{'id': rental_item.pk, 'qty_returned': 1, 'condition': 'ok'}],
                # The tape is not listed at all and counts as not returned.
                'consumables': [
                    {'id': cables.pk, 'qty_returned': 2, 'note': 'one lost'},
                    {'id': card.pk, 'qty_returned': 1},
                ],
                'email_receipt': True,
                'close_rental': True,
            }),
            content_type='application/json',
        )

    assert response.status_code == 200, response.content
    rental.refresh_from_db()
    assert rental.status == 'closed'
    cables.refresh_from_db()
    card.refresh_from_db()
    tape.refresh_from_db()
    assert (cables.status, cables.quantity_missing, cables.notes) == ('missing', 1, 'one lost')
    assert card.status == 'returned'
    assert tape.status == 'missing'
    missing_items = mocked_receipt.call_args.kwargs['missing_items']
    assert missing_items == [
        {'name': 'XLR 5m', 'quantity': 1},
        {'name': 'Gaffer', 'quantity': 1},
    ]

    missing_page = client.get(reverse('rental:missing_consumables'))
    assert [row['consumable'].name for row in missing_page.context['rows']] == ['XLR 5m', 'Gaffer']


@pytest.mark.django_db
def test__rental__consumables__resolve_missing(client, django_user_model):
    borrower, staff = _users(django_user_model)
    rental = _rental(borrower, staff, status='closed')
    missing = RentalConsumable.objects.create(
        rental_request=rental, name='XLR', quantity=2, quantity_returned=1,
        status=RentalConsumable.STATUS_MISSING, returned_at=timezone.now())
    lost = RentalConsumable.objects.create(
        rental_request=rental, name='Card', quantity=1,
        status=RentalConsumable.STATUS_MISSING, returned_at=timezone.now())
    left_out = RentalConsumable.objects.create(rental_request=rental, name='Tape', quantity=1)
    client.force_login(staff)
    url = 'rental:resolve_consumable'

    response = client.post(reverse(url, args=[rental.pk, missing.pk]),
                           {'action': 'returned', 'back_to': 'missing'})
    client.post(reverse(url, args=[rental.pk, lost.pk]), {'action': 'written_off'})
    client.post(reverse(url, args=[rental.pk, left_out.pk]), {'action': 'missing'})

    assert response['Location'] == reverse('rental:missing_consumables')
    missing.refresh_from_db()
    lost.refresh_from_db()
    left_out.refresh_from_db()
    assert (missing.status, missing.quantity_returned, missing.resolved_by) == ('returned', 2, staff)
    assert lost.status == 'written_off'
    assert left_out.status == 'missing'
    assert left_out.returned_at is not None


@pytest.mark.django_db
def test__rental__consumables__reminder_every_interval(django_user_model, settings):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    borrower, staff = _users(django_user_model)
    config = RentalConfig.get_config()
    config.missing_consumable_reminder_days = 7
    config.save()
    old_rental = _rental(borrower, staff, status='closed', project='Old shoot')
    new_rental = _rental(borrower, staff, status='closed', project='New shoot')
    eight_days_ago = timezone.now() - timedelta(days=8)
    due = [
        RentalConsumable.objects.create(
            rental_request=old_rental, name='XLR 5m', quantity=3, quantity_returned=1,
            status=RentalConsumable.STATUS_MISSING, returned_at=eight_days_ago),
        RentalConsumable.objects.create(
            rental_request=new_rental, name='SD 64GB', quantity=1,
            status=RentalConsumable.STATUS_MISSING, returned_at=eight_days_ago),
    ]
    # Returned yesterday: too early for a reminder.
    RentalConsumable.objects.create(
        rental_request=new_rental, name='Gaffer', quantity=1,
        status=RentalConsumable.STATUS_MISSING, returned_at=timezone.now() - timedelta(days=1))

    call_command('send_return_reminders')

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['borrower@example.com']
    body = mail.outbox[0].body
    assert '2 x XLR 5m' in body
    assert '1 x SD 64GB' in body
    assert 'Gaffer' not in body
    for consumable in due:
        consumable.refresh_from_db()
        assert consumable.reminder_count == 1

    # Not again within the interval.
    call_command('send_return_reminders')
    assert len(mail.outbox) == 1

    # Again once the interval passed.
    RentalConsumable.objects.filter(pk__in=[c.pk for c in due]).update(
        last_reminder_sent_at=eight_days_ago)
    call_command('send_return_reminders')
    assert len(mail.outbox) == 2

    config.missing_consumable_reminder_days = 0
    config.save()
    RentalConsumable.objects.update(last_reminder_sent_at=eight_days_ago)
    call_command('send_return_reminders')
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test__rental__consumables__wizard_creates_and_warns_about_missing(client, django_user_model):
    borrower, staff = _users(django_user_model)
    old_rental = _rental(borrower, staff, status='closed')
    RentalConsumable.objects.create(
        rental_request=old_rental, name='XLR 5m', quantity=2,
        status=RentalConsumable.STATUS_MISSING, returned_at=timezone.now())
    client.force_login(staff)

    assert serialize_user(borrower)['warn'] == 'Missing consumables: XLR 5m (2)'
    assert serialize_user(staff)['warn'] is None

    with patch('rental.views.RentalService.create_rental_request') as create:
        new_rental = _rental(borrower, staff, status='reserved', project='New')
        create.return_value = {'success': True, 'rental_id': new_rental.pk}
        response = client.post(
            reverse('rental:create_submit'),
            data=json.dumps({'user_id': borrower.pk, 'project': 'New', 'consumables': 'SD 64GB - 4'}),
            content_type='application/json',
        )

    assert response.status_code == 200, response.content
    assert list(new_rental.consumables.values_list('name', 'quantity')) == [('SD 64GB', 4)]
