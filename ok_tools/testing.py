from datetime import datetime
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from registration.models import Profile
import PyPDF2
import io


User = get_user_model()


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


def create_user(user_dict, verified=False, is_staff=False) -> User:
    """Create a user with a profile."""
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
