from .models import License
from .models import YouthProtectionCategory
from datetime import date
from django.conf import settings
from django.http import FileResponse
from django.utils.translation import gettext as _
from fdfgen import forge_fdf
import io
import os
import subprocess
import tempfile


# find out fields using
# pdftk ./licenses/files/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf dump_data_fields

PDFTK_CANDIDATES = ['/opt/homebrew/bin/pdftk', '/usr/bin/pdftk']
PDFTK = None

for candidate in PDFTK_CANDIDATES:
    if os.path.isfile(candidate):
        PDFTK = candidate

if PDFTK is None:
    raise SystemError(f'pdftk not found in {PDFTK_CANDIDATES}')


def choose(value):
    """Convert boolean-like value into 'yes', 'no', or 'unbekannt'.

    Args:
        value: Any input value to evaluate.

    Returns:
        str: 'yes' if truthy, 'no' if falsy, 'unbekannt' if None.
    """
    if value is None:
        return 'unbekannt'
    if value:
        return 'yes'
    return 'no'


def val(value):
    """Return the value if not empty, otherwise an empty string.

    Args:
        value: Any input value.

    Returns:
        str: The input value or an empty string.
    """
    if value:
        return value
    return ''


def generate_license_file(lr: License) -> FileResponse:
    """Generate a License as pdf file.

    As template the '2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf' from
    https://www.okmq.de/images/Formulare/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf
    is used.
    The function assumes that the License has a user with profile.
    """
    user = lr.profile.okuser
    profile = lr.profile

    fields = [
        ('name', f'{val(profile.first_name)} {val(profile.last_name)}'),
        ('street', f'{val(profile.street)} {val(profile.house_number)}'),
        ('zip_city', f'{val(profile.zipcode)} {val(profile.city)}'),
        ('phone', f'{val(profile.phone_number)} {val(profile.mobile_number)}'),
        ('email', val(user.email)),
        ('title', val(lr.title)),
        ('subtitle', val(lr.subtitle)),
        ('length', val(lr.duration)),
        ('repetitions_allowed', choose(lr.repetitions_allowed)),
        ('media_authority_exchange_allowed', choose(lr.media_authority_exchange_allowed)),
        ('media_authority_exchange_allowed_other_states', choose(lr.media_authority_exchange_allowed_other_states)),
        ('store_in_ok_media_library', choose(lr.store_in_ok_media_library)),
        ('youth_protection_necessary', choose(lr.youth_protection_necessary)),
        ('youth_protection_category', str(lr.youth_protection_category)),
        ('city_date_member', f'{val(profile.city)} {date.today().strftime(settings.DATE_INPUT_FORMATS)}')
    ]

    with tempfile.TemporaryDirectory() as tmpdirname:
        fdf = forge_fdf("", fields, [], [], [])
        with open(os.path.join(tmpdirname, "data.fdf"), "wb") as fdf_file:
            fdf_file.write(fdf)
        result = subprocess.run(
            [PDFTK,
            'licenses/files/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf',
            'fill_form',
            os.path.join(tmpdirname, "data.fdf"),
            'output',
            os.path.join(tmpdirname, "output.pdf")])
        with open(os.path.join(tmpdirname, "output.pdf"), "rb") as output:
            result = output.read()

    apl_stream = io.BytesIO()
    apl_stream.write(result)
    apl_stream.seek(0)

    return FileResponse(apl_stream, filename=_('license.pdf'))
