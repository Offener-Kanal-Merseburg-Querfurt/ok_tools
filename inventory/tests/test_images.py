"""Tests for the cached photo derivatives (thumbnail and lightbox preview)."""

from inventory import images
from inventory.images import ensure_preview
from inventory.images import ensure_thumbnail
from inventory.models import InventoryImageConfig
from inventory.models import InventoryItem
from inventory.models import InventoryItemImage
from inventory.models import Location
from PIL import Image
import pytest


@pytest.fixture
def photo(db, tmp_path, settings):
    """A 4000x6000 source photo wired to an item, served from tmp_path."""
    settings.MEDIA_ROOT = str(tmp_path / 'media')

    config = InventoryImageConfig.get_config()
    config.base_path = str(tmp_path / 'photos')
    config.thumbnails_beside_originals = False
    config.save()

    location = Location.objects.create(name='Test Room')
    item = InventoryItem.objects.create(
        inventory_number='OK-IMG-1', quantity=1, location=location)
    folder = tmp_path / 'photos' / item.inventory_number
    folder.mkdir(parents=True)
    source = folder / 'big.jpg'
    Image.new('RGB', (4000, 6000), (30, 90, 200)).save(source, 'JPEG')

    return InventoryItemImage.objects.create(
        item=item,
        filename='big.jpg',
        relative_path=f'{item.inventory_number}/big.jpg',
        is_available=True,
    )


def _size(path):
    with Image.open(path) as img:
        return img.size


def test_thumbnail_capped_at_400_longest_edge(photo):
    width, height = _size(ensure_thumbnail(photo))
    assert max(width, height) == 400
    # Aspect ratio preserved: 4000x6000 -> 267x400.
    assert (width, height) == (267, 400)


def test_preview_capped_at_1600_longest_edge(photo):
    width, height = _size(ensure_preview(photo))
    assert max(width, height) == 1600
    assert (width, height) == (1067, 1600)


def test_preview_is_smaller_than_original_and_distinct_from_thumb(photo):
    thumb = ensure_thumbnail(photo)
    preview = ensure_preview(photo)

    # Three different files: thumbnail, preview, original all coexist.
    assert thumb != preview
    assert thumb.is_file() and preview.is_file()
    assert preview.stat().st_size < photo.abs_path().stat().st_size


def test_thumbnail_keeps_its_historical_unsuffixed_name(photo):
    """The thumbnail filename must not change, or existing caches would rot."""
    thumb = ensure_thumbnail(photo)
    preview = ensure_preview(photo)
    assert '_1600' not in thumb.name
    assert '_1600' in preview.name


def test_delete_thumbnail_removes_every_variant(photo):
    thumb = ensure_thumbnail(photo)
    preview = ensure_preview(photo)
    assert thumb.is_file() and preview.is_file()

    images.delete_thumbnail(photo)

    assert not thumb.exists()
    assert not preview.exists()


@pytest.mark.parametrize('url_name', [
    'inventory:item_image', 'inventory:item_image_thumb', 'inventory:item_image_preview'])
def test_rental_user_sees_photos_of_rentable_items(photo, client, django_user_model, url_name):
    """The user rental dashboard shows these photos, so no staff login is needed."""
    from django.urls import reverse
    photo.item.available_for_rent = True
    photo.item.save()
    client.force_login(django_user_model.objects.create_user(
        email='renter@example.com', password='pw'))

    resp = client.get(reverse(url_name, args=[photo.pk]))

    assert resp.status_code == 200
    assert resp['Content-Type'] == 'image/jpeg'


def test_rental_user_cannot_see_photos_of_items_not_for_rent(photo, client, django_user_model):
    from django.urls import reverse
    photo.item.available_for_rent = False
    photo.item.save()
    client.force_login(django_user_model.objects.create_user(
        email='renter@example.com', password='pw'))

    resp = client.get(reverse('inventory:item_image_thumb', args=[photo.pk]))

    assert resp.status_code == 404


def test_anonymous_photo_request_goes_to_the_user_login(photo, client):
    from django.urls import reverse
    resp = client.get(reverse('inventory:item_image_thumb', args=[photo.pk]))

    assert resp.status_code == 302
    assert '/admin/login/' not in resp['Location']
