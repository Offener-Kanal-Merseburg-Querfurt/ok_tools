from .admin import InventoryResource
from .images import ensure_preview
from .images import ensure_thumbnail
from .models import InventoryImageConfig
from .models import InventoryItemImage
from .services import InventoryService
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
import mimetypes
import os


@staff_member_required
def export_inventory_items(request):
    """Export all inventory items as an Excel file."""
    inventory_service = InventoryService()
    dataset = inventory_service.export_inventory_items()
    response = HttpResponse(dataset.xlsx, content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename="inventory_items.xlsx"'
    return response


def _get_visible_image(request, image_id):
    """Return the item photo ``request.user`` may see, or raise 404.

    Staff see every photo. Other signed-in users only see photos of items that
    are offered for rent, because the rental dashboard shows those to them.
    """
    images = InventoryItemImage.objects.all()
    if not request.user.is_staff:
        images = images.filter(item__available_for_rent=True)
    return get_object_or_404(images, pk=image_id)


@login_required
def serve_item_image(request, image_id):
    """Stream an inventory item photo from the mounted folder.

    The photos folder lives outside ``MEDIA_ROOT`` so Django does not serve it
    directly. Access requires a login (see ``_get_visible_image``) and the
    resolved path is validated to stay inside the configured base directory
    (guards against traversal).
    """
    image = _get_visible_image(request, image_id)

    base_dir = InventoryImageConfig.get_config().get_base_dir()
    if base_dir is None:
        raise Http404('Photos folder is not configured.')

    abs_path = (base_dir / image.relative_path).resolve()
    base_resolved = base_dir.resolve()

    # Prevent path traversal: the file must live inside the base directory.
    if os.path.commonpath([str(base_resolved), str(abs_path)]) != str(base_resolved):
        raise Http404('Invalid image path.')
    if not abs_path.is_file():
        raise Http404('Image file not found.')

    content_type, _enc = mimetypes.guess_type(str(abs_path))
    return FileResponse(
        open(abs_path, 'rb'),
        content_type=content_type or 'application/octet-stream',
    )


@login_required
def serve_item_image_thumbnail(request, image_id):
    """Stream a small cached thumbnail for an inventory item photo.

    Falls back to the original file if a thumbnail cannot be produced (e.g.
    Pillow unavailable), so the gallery always renders something.
    """
    image = _get_visible_image(request, image_id)

    thumb_path = ensure_thumbnail(image)
    if thumb_path is None:
        # No thumbnail available; serve the original as a graceful fallback.
        return serve_item_image(request, image_id)

    return FileResponse(open(thumb_path, 'rb'), content_type='image/jpeg')


@login_required
def serve_item_image_preview(request, image_id):
    """Stream a downscaled preview for the lightbox.

    Much lighter than the original (longest edge capped at ~1600px) yet sharp
    on a full screen, so the modal opens quickly. Falls back to the original
    when a preview cannot be produced.
    """
    image = _get_visible_image(request, image_id)

    preview_path = ensure_preview(image)
    if preview_path is None:
        return serve_item_image(request, image_id)

    return FileResponse(open(preview_path, 'rb'), content_type='image/jpeg')
