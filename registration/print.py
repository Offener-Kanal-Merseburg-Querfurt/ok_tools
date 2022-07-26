from .models import OKUser as User
from .models import Profile
from PyPDF2 import PdfFileReader
from PyPDF2 import PdfFileWriter
from django.conf import settings
from django.http import FileResponse
from django.utils.translation import gettext as _
from reportlab.pdfgen import canvas
import io


def _f_number(p): return str(p) if p else '     -     '


def generate_registration_form(user: User, profile: Profile) -> FileResponse:
    """
    Generate an registration form as pdf using the given user data.

    As template the 'Nutzerkartei_Anmeldung_2017.pdf' from
    https://www.okmq.de/images/Formulare/Nutzerkartei_Anmeldung_2017.pdf
    is used.
    """
    pdf_buffer = io.BytesIO()

    pdf_edits = canvas.Canvas(pdf_buffer)

    pdf_edits.setFontSize(7.5)
    COL_1 = 130
    COL_2 = 370

    ROW_1 = 585
    ROW_2 = 546
    ROW_3 = 507
    ROW_4 = 468
    ROW_5 = 438

    # Vorname
    pdf_edits.drawString(COL_1, ROW_1, profile.first_name)
    # Name
    pdf_edits.drawString(COL_2, ROW_1, profile.last_name)
    # Ort
    pdf_edits.drawString(COL_1, ROW_2, f'{profile.zipcode} {profile.city}')
    # Straße
    pdf_edits.drawString(COL_2, ROW_2,
                         f' {profile.street} {profile.house_number}',
                         )
    # Geburtstag
    pdf_edits.drawString(COL_1, ROW_3,
                         profile.birthday.strftime(
                             settings.DATE_INPUT_FORMATS),
                         )
    # Telefon privat
    pdf_edits.drawString(COL_1, ROW_4, _f_number(profile.phone_number))
    # dienstlich
    pdf_edits.drawString(COL_2, ROW_4, _f_number(profile.mobile_number))
    # e-mail
    pdf_edits.drawString(COL_1, ROW_5, user.email)

    pdf_edits.showPage()
    pdf_edits.save()

    pdf_buffer.seek(0)

    edit_pdf = PdfFileReader(pdf_buffer)

    with open('files/Nutzerkartei_Anmeldung_2017.pdf', 'rb') as fileobj:
        registration_template = PdfFileReader(fileobj)

        regstr_page = registration_template.getPage(0)

        regstr_page.mergePage(edit_pdf.getPage(0))

        registration = PdfFileWriter()
        registration.addPage(regstr_page)
        apl_stream = io.BytesIO()
        registration.write(apl_stream)

        apl_stream.seek(0)

    return FileResponse(apl_stream, filename=_('registration_form.pdf'))
