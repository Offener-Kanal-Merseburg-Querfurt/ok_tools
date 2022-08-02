from django.urls import reverse_lazy
from licenses.models import LicenseRequest
import PyPDF2
import io


# Global helper functions and constants

PWD = 'testpassword'
DOMAIN = 'http://localhost:8000'


def pdfToText(pdf) -> str:
    """Convert pdf bytes into text."""
    reader = PyPDF2.PdfReader(io.BytesIO(pdf))

    return "\n".join(page.extract_text() for page in reader.pages)


def log_in(browser, email, password):
    """Log in a user with the given email and password."""
    browser.open(f'{DOMAIN}{reverse_lazy("login")}')
    assert 'profile/login/' in browser.url, \
        f'Not on login page, URL is {browser.url}'

    browser.getControl('Email').value = email
    browser.getControl('Password').value = password
    browser.getControl('Log In').click()


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
