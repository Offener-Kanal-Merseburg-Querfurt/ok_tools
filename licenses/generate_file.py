from .models import LicenseRequest
from PyPDF2 import PdfReader
from PyPDF2 import PdfWriter
from datetime import date
from django.conf import settings
from django.http import FileResponse
from django.utils.translation import gettext as _
from reportlab.pdfgen import canvas
import io


def f(p):
    """Return a readable data representation."""
    if p:
        return str(p)
    else:
        return '  -------  '


def generate_license_file(user, lr: LicenseRequest) -> FileResponse:
    """
    Generate a License as pdf file.

    As template the '2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf' from
    https://www.okmq.de/images/Formulare/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf
    is used.
    The function assumes that the LicenseRequest has a user with profile.
    """
    TEXTSIZE = 7.5

    # page 1
    pdf_buffer = io.BytesIO()
    pdf_edits = canvas.Canvas(pdf_buffer)
    pdf_edits.setFontSize(TEXTSIZE)

    COL_1 = 180
    X_MOBILE = 370
    X_SEND_DATE = 315
    Y_NAME = 636
    Y_STREET = 614
    Y_ZIP = 592
    Y_PHONE = 571
    Y_MAIL = 548
    Y_TITLE = 450
    Y_SUBTITLE = 424
    Y_DURATION = 399
    Y_SEND_DATE = 370

    user = lr.okuser

    profile = user.profile

    # Herr/Frau
    pdf_edits.drawString(
        COL_1, Y_NAME, f'{profile.first_name} {profile.last_name}')

    # Straße
    pdf_edits.drawString(
        COL_1, Y_STREET, f'{profile.street} {profile.house_number}')

    # PLZ/Ort
    pdf_edits.drawString(COL_1, Y_ZIP, f'{profile.zipcode} {profile.city}')

    # Telefon
    pdf_edits.drawString(COL_1, Y_PHONE, f(profile.phone_number))

    # Mobil
    pdf_edits.drawString(X_MOBILE, Y_PHONE, f(profile.mobile_number))

    # email
    pdf_edits.drawString(COL_1, Y_MAIL, f(user.email))

    # Titel
    pdf_edits.drawString(COL_1, Y_TITLE, f(lr.title))

    # Untertitel
    pdf_edits.drawString(COL_1, Y_SUBTITLE, f(lr.subtitle))

    # Länge
    pdf_edits.drawString(COL_1, Y_DURATION, f(lr.duration))

    # Sendetermin
    pdf_edits.drawString(X_SEND_DATE, Y_SEND_DATE, f(lr.suggested_date))

    pdf_edits.showPage()
    pdf_edits.save()
    pdf_buffer.seek(0)

    edit_page1 = PdfReader(pdf_buffer)

    # page 2
    pdf_buffer = io.BytesIO()
    pdf_edits = canvas.Canvas(pdf_buffer)
    pdf_edits.setFontSize(TEXTSIZE)

    X_YES = 458
    X_NO = 492
    X_SIGN = 120

    Y_REPEAT = 472
    Y_SHARE = 429
    Y_YOUTH = 392
    Y_SIGN = 233

    pdf_edits.drawString(
        X_SIGN,
        Y_SIGN,
        f'{profile.city}, {date.today().strftime(settings.DATE_INPUT_FORMATS)}'
    )

    # Yes/No-Fields
    pdf_edits.setFontSize(20)

    def choose(v):
        """Set Position depending on boolean."""
        if v:
            return X_YES
        else:
            return X_NO

    pdf_edits.drawString(choose(lr.repetitions_allowed), Y_REPEAT, 'x')
    pdf_edits.drawString(
        choose(lr.media_authority_exchange_allowed), Y_SHARE, 'x')
    pdf_edits.drawString(choose(lr.youth_protection_necessary), Y_YOUTH, 'x')

    pdf_edits.showPage()
    pdf_edits.save()
    pdf_buffer.seek(0)

    edit_page2 = PdfReader(pdf_buffer)

    # required until seek
    with open(
        'licenses/files/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf',
        'rb'
    ) as fileobj:

        license_template = PdfReader(fileobj)

        page1 = license_template.pages[0]
        page1.merge_page(edit_page1.pages[0])

        page2 = license_template.pages[1]
        page2.merge_page(edit_page2.pages[0])

        license_file = PdfWriter()
        license_file.add_page(page1)
        license_file.add_page(page2)
        apl_stream = io.BytesIO()
        license_file.write(apl_stream)

        apl_stream.seek(0)

    return FileResponse(apl_stream, filename=_('license_request.pdf'))
