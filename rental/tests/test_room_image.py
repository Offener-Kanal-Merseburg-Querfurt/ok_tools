"""Tests for serving room photos through a Django view.

In the split deployment nginx runs on a separate VM and cannot see the app's
MEDIA_ROOT, so room photos are streamed by ``serve_room_image`` instead of a
static ``/media/`` URL.
"""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test import TestCase
from django.urls import reverse
from rental.models import Room
from rental.models import RoomImage
from PIL import Image
import io

User = get_user_model()


def _jpeg_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (120, 80), (80, 120, 200)).save(buf, 'JPEG')
    return buf.getvalue()


class ServeRoomImageTests(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user(
            email='roomstaff@example.com', password='pw', is_staff=True)
        self.room = Room.objects.create(
            name='Regieraum', capacity=5, is_active=True)
        self.image = RoomImage.objects.create(
            room=self.room,
            image=SimpleUploadedFile(
                'room.jpg', _jpeg_bytes(), content_type='image/jpeg'),
        )
        self.url = reverse('rental:room_image', args=[self.image.pk])

    def tearDown(self):
        from rental.views import _room_thumbnail_path
        _room_thumbnail_path(self.image).unlink(missing_ok=True)
        self.image.image.delete(save=False)

    def test_staff_gets_the_image_bytes(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')
        body = b''.join(resp.streaming_content)
        self.assertGreater(len(body), 0)

    def test_thumb_size_is_downscaled(self):
        from PIL import Image
        import io
        self.client.force_login(self.staff)
        resp = self.client.get(self.url + '?size=thumb')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')
        thumb = Image.open(io.BytesIO(b''.join(resp.streaming_content)))
        # Longest edge capped at the inventory thumbnail size (400px).
        self.assertLessEqual(max(thumb.size), 400)

    def test_anonymous_is_redirected_to_the_user_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('/admin/login/', resp['Location'])

    def test_rental_user_sees_photos_of_active_rooms(self):
        self.client.force_login(User.objects.create_user(
            email='roomrenter@example.com', password='pw'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')

    def test_rental_user_cannot_see_photos_of_inactive_rooms(self):
        self.room.is_active = False
        self.room.save()
        self.client.force_login(User.objects.create_user(
            email='roomrenter@example.com', password='pw'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_missing_image_row_returns_404(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('rental:room_image', args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_admin_change_page_never_links_room_photos_via_media(self):
        import re
        self.client.force_login(
            User.objects.create_superuser(email='su@example.com', password='pw'))
        html = self.client.get(
            f'/admin/rental/room/{self.room.id}/change/').content.decode()
        view_url = f'/rental/room-image/{self.image.pk}/'

        # Preview thumbnail goes through the view.
        preview_imgs = [t for t in re.findall(r'<img[^>]+>', html)
                        if 'object-fit:cover' in t]
        self.assertTrue(preview_imgs)
        self.assertIn(view_url, preview_imgs[0])

        # The widget's "Currently" link goes through the view too.
        current = re.search(r'(?:Currently|Aktuell):\s*<a href="([^"]+)"', html)
        self.assertIsNotNone(current)
        self.assertEqual(current.group(1), view_url)

        # No room photo is linked via the static /media/ path anywhere.
        self.assertNotIn('/media/room_photos', html)
