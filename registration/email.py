from .models import Profile
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template import loader
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
import logging


logger = logging.getLogger('django')
UserModel = get_user_model()


def _send_auth_mail(
    subject_template_name,
    email_template_name,
    context,
    from_email,
    to_email,
):
    """
    Send a django.core.mail.EmailMultiAlternatives to `to_email`.

    Copied from https://github.com/django/django/blob/48501c84ad54971af25c10b3544aee91b6275c86/django/contrib/auth/forms.py#L262 # noqa
    """
    subject = loader.render_to_string(subject_template_name, context)
    # Email subject *must not* contain newlines
    subject = "".join(subject.splitlines())
    body = loader.render_to_string(email_template_name, context)

    email_message = EmailMultiAlternatives(
        subject, body, from_email, [to_email])
    # not relevant yet because no template is used

    # if html_email_template_name is not None:
    #   html_email = loader.render_to_string(html_email_template_name, context)
    #     email_message.attach_alternative(html_email, "text/html")

    email_message.send()


def send_auth_mail(
    email,
    subject_template_name="registration/password_set_subject_customized.txt",
    email_template_name="registration/password_set_email_customized.html",
    use_https=False,
    token_generator=default_token_generator,
    from_email=settings.EMAIL_HOST_USER,
    extra_email_context=None,
):
    """Generate link for setting password and send it to the user."""
    try:
        user = UserModel.objects.get(Q(email__iexact=email))
        profile = Profile.objects.get(okuser=user)
    except UserModel.DoesNotExist:
        logger.error(f'User with E-Mail {email} does not exist.')
        raise
    except Profile.DoesNotExist:
        logger.error(f'Profile for user {email} does not exist.')
        raise

    context = {
        "first_name": profile.first_name,
        "email": email,
        "domain": 'localhost:8000',  # TODO nicht hartcodieren
        "ok_name": settings.OK_NAME,
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "user": user,
        "token": token_generator.make_token(user),
        "protocol": "https" if use_https else "http",
        **(extra_email_context or {}),
    }
    _send_auth_mail(
        subject_template_name,
        email_template_name,
        context,
        from_email,
        email,
    )
