from .email import send_auth_mail
from .forms import ProfileForm
from .models import Profile
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.views import generic
import django.contrib.auth.forms
import functools
import logging


class RegisterView(generic.CreateView):
    """A view which shows the form to register a user."""

    model = Profile
    form_class = form = ProfileForm
    template_name = 'registration/register.html'

    def post(self, request):
        """Create a new user, if the email address is not used yet."""
        form = self.form(request.POST)

        if not form.is_valid():
            error_list = functools.reduce(sum, list(form.errors.values()))
            logging.error('Received invalid RegisterForm')
            # TODO send as message
            return HttpResponseBadRequest('Invalid Form:\n\n {}'
                                          .format("\n\n".join(error_list)))

        data = form.cleaned_data

        user_model = get_user_model()
        email = data['email'].lower()

        # Does the user already exist?
        if user_model.objects.filter(email=email):
            return HttpResponseBadRequest(
                f'The e-mail address {email} already exists.')

        user = user_model.objects.create_user(email=email)
        user.save()
        send_auth_mail(email)
        profile = self.model(
            okuser=user,
            first_name=data['first_name'].lower(),
            last_name=data['last_name'].lower(),
            gender=data['gender'],
            phone_number=data['mobile_number'],
            mobile_number=data['phone_number'],
            birthday=data['birthday'],
            street=data['street'].lower(),
            house_number=data['house_number'],
            zipcode=data['zipcode'],
            city=data['city'],
        )

        profile.save()
        return HttpResponse(f'Successfully created user {user.email}')


class PasswordResetView(auth_views.PasswordResetView):
    """
    Overwrite the get_form_class function.

    Because otherwise get_form_class returns None. The reason for that
    behavior is not known.
    """

    def get_form_class(self):
        """Return PasswordResetForm explicitly."""
        return django.contrib.auth.forms.PasswordResetForm


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """
    Overwrite the get_form_class function.

    Because otherwise get_form_class returns None. The reason for that
    behavior is not known.
    """

    def get_form_class(self):
        """Return SetPasswordForm explicitly."""
        return django.contrib.auth.forms.SetPasswordForm
