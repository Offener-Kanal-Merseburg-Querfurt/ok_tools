from datetime import datetime
from django.conf import settings
from django.contrib.auth import get_user_model
from licenses.models import LicenseRequest
from registration.models import Profile
import PyPDF2
import io


User = get_user_model()


# Global helper functions and constants

EMAIL = "user@example.com"
PWD = 'testpassword'
DOMAIN = 'http://localhost:8000'


def pdfToText(pdf) -> str:
    """Convert pdf bytes into text."""
    reader = PyPDF2.PdfReader(io.BytesIO(pdf))

    return "\n".join(page.extract_text() for page in reader.pages)


def create_user(user_dict, verified=False, is_staff=False) -> User:
    """Create a user with an unverified profile."""
    user = User.objects.create_user(
        user_dict['email'], password=PWD, is_staff=is_staff)
    Profile(
        okuser=user,
        first_name=user_dict['first_name'],
        last_name=user_dict['last_name'],
        gender=user_dict['gender'],
        phone_number=user_dict['mobile_number'],
        mobile_number=user_dict['phone_number'],
        birthday=datetime.strptime(
            user_dict['birthday'], settings.DATE_INPUT_FORMATS).date(),
        street=user_dict['street'],
        house_number=user_dict['house_number'],
        zipcode=user_dict['zipcode'],
        city=user_dict['city'],
        verified=verified,
    ).save()

    return user


def create_license_request(
        user, category, license_template_dict) -> LicenseRequest:
    """
    Create a LicenseRequest.

    license_template_dict contains all data of an LicenseTemplate.
    """
    return LicenseRequest.objects.create(
        okuser=user,
        category=category,
        title=license_template_dict['title'],
        subtitle=license_template_dict['subtitle'],
        description=license_template_dict['description'],
        duration=license_template_dict['duration'],
        suggested_date=license_template_dict['suggested_date'],
        repetitions_allowed=license_template_dict['repetitions_allowed'],
        media_authority_exchange_allowed=license_template_dict[
            'media_authority_exchange_allowed'],
        youth_protection_necessary=license_template_dict[
            'youth_protection_necessary'],
        store_in_ok_media_library=license_template_dict[
            'store_in_ok_media_library'],
    )