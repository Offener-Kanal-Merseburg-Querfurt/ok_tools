from django.urls import reverse_lazy
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
