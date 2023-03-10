from .email import send_mail
from django.conf import settings
from django.dispatch import Signal
from django.dispatch import receiver
import logging


logger = logging.getLogger('django')


signal = Signal()


@receiver(signal)
def send_verification_mail(sender, obj=None, request=None, **kwargs):
    """Send the mail, if the profile was verified."""
    assert obj.verified
    if obj.okuser is None:
        # no email when the profile has no user
        return

    send_mail(
        email_template_name='email/confirm_verification_body.html',
        subject_template_name='email/confirm_verification_subject.txt',
        context={
            "first_name": obj.first_name,
            "ok_name": settings.OK_NAME,
            "domain": request.get_host(),
        },
        from_email=settings.EMAIL_HOST_USER,
        to_email=obj.okuser.email,
    )
