from django.http import FileResponse
import io
import qrcode


def generate_qr_code(request, url) -> FileResponse:
    """Generate a qr code storing the given url."""
    qr = qrcode.QRCode()
    qr.add_data(url)
    qr.make(fit=True)
    img_bytes = io.BytesIO()
    img = qr.make_image(fill_collor='black', back_collor='white')
    img.save(img_bytes, type='PNG')
    img_bytes.seek(0)
    return FileResponse(img_bytes, filename=('qr.png'))
