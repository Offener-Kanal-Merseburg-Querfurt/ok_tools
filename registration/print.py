from .models import OKUser as User
from .models import Profile
from datetime import date
from django.conf import settings
from django.http import FileResponse
from django.utils.translation import gettext as _
from fdfgen import forge_fdf
import io
import os
import subprocess
import tempfile


# Search for the pdftk executable among possible candidates
PDFTK_CANDIDATES = ['/opt/homebrew/bin/pdftk', '/usr/bin/pdftk', 'C:\\Program Files (x86)\\PDFtk Server\\bin\\pdftk.exe']
PDFTK = next((c for c in PDFTK_CANDIDATES if os.path.isfile(c)), None)
if not PDFTK:
    raise RuntimeError(f'pdftk not found in {PDFTK_CANDIDATES}')

def val(value):
    """Return the value if set, otherwise an empty string."""
    if value:
        return value
    return ''

def _f_number(p):
    """Return a string representation of a number or a placeholder if the value is missing."""
    return str(p) if p else '     -     '

def generate_registration_form(user: User, profile: Profile) -> FileResponse:
    """Generate a registration form in PDF format.

    This function uses the PDF template
    'files/Nutzerkartei_Anmeldung_2022.pdf' and fills it with user data.

    It is assumed that the PDF template contains fields with the following names:
      - first_name
      - last_name
      - zip_city
      - street
      - birthday
      - phone
      - mobile
      - email

    Returns:
        FileResponse: A response containing the filled-out PDF form.
    """
    # Path to the PDF template
    template_pdf = os.path.join(settings.BASE_DIR, 'files', 'Nutzerkartei_Anmeldung_2022_n.pdf')
    if not os.path.isfile(template_pdf):
        raise FileNotFoundError(f'PDF template not found: {template_pdf}')

    # Forming a list of "field name" — "value" pairs
    fields = [
        ('first_name', profile.first_name),
        ('last_name', profile.last_name),
        ('zip_city', f'{profile.zipcode} {profile.city}'),
        ('street', f'{profile.street} {profile.house_number}'),
        ('birthday', profile.birthday.strftime('%d.%m.%Y') if profile.birthday else ''),
        ('phone', _f_number(profile.phone_number)),
        ('mobile', _f_number(profile.mobile_number)),
        ('email', getattr(user, 'email', '')),
        ('city_date_member', f'{val(profile.city)} {date.today().strftime(settings.DATE_INPUT_FORMATS)}')
    ]

    # Create a temporary directory for the FDF file and output PDF
    with tempfile.TemporaryDirectory() as tmpdirname:
        # Generate FDF data
        fdf_data = forge_fdf("", fields, [], [], [])
        fdf_path = os.path.join(tmpdirname, "data.fdf")
        with open(fdf_path, "wb") as fdf_file:
            fdf_file.write(fdf_data)

        # Define the path for the output PDF
        output_pdf = os.path.join(tmpdirname, "output.pdf")

        # Run pdftk to fill out the form
        try:
            subprocess.run(
                [PDFTK, template_pdf, 'fill_form', fdf_path, 'output', output_pdf, 'flatten'],
                check=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f'Error executing pdftk: {e}')

        # Read the completed PDF file
        with open(output_pdf, "rb") as pdf_file:
            pdf_result = pdf_file.read()

    # Return the PDF as a FileResponse
    pdf_stream = io.BytesIO(pdf_result)
    pdf_stream.seek(0)
    return FileResponse(pdf_stream, filename=_('registration_form.pdf'))
