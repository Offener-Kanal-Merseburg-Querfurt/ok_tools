from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template import loader
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
import logging


UserModel = get_user_model()


def _send_auth_mail(
    subject_template_name,
    email_template_name,
    context,
    from_email,
    to_email,
    html_email_template_name=None,
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
    if html_email_template_name is not None:
        html_email = loader.render_to_string(html_email_template_name, context)
        email_message.attach_alternative(html_email, "text/html")

    email_message.send()


def send_auth_mail(
    email,
    subject_template_name="registration/password_reset_subject.txt",
    email_template_name="registration/password_reset_email.html",
    use_https=False,
    token_generator=default_token_generator,
    from_email=None,
    html_email_template_name=None,
    extra_email_context=None,
):
    """Generate link for setting password and send it to the user."""
    try:
        user = UserModel.objects.get(Q(email__iexact=email))
    except UserModel.DoesNotExist:
        # TODO logging messages should be delivered to front end
        logging.error(f'User with E-Mail {email} does not exist.')
        raise
    except UserModel.MutlipleObjectsReturned:
        logging.error(
            f'There are more then one user with the E-Mail {email}.')
        raise

    context = {
        "email": email,
        "domain": 'localhost:8000',  # TODO nicht hartcodieren
        "site_name": settings.OK_NAME,
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
        html_email_template_name=html_email_template_name,
    )
