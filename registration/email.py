from django.conf import settings
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _


def send_auth_email(email):
    """Send an email with a link to set the password."""
    SUBJECT = _('Welcome to the Offener Kanal!')
    MESSAGE: str = (
        _('Thank you for your registration. ') +
        _('Please finish your registration by clicking on the following'
          ' link and choose a password.\n\n') +
        'THE LINK\n\n' +
        _('Best regards\n') +
        settings.OK_NAME
    )

    send_mail(
        subject=SUBJECT,
        message=MESSAGE,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[email]
    )
