from .email import send_auth_mail
from .forms import PasswordResetForm
from .forms import ProfileForm
from .forms import UserDataForm
from .models import Profile
from .print import generate_registration_form
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import generic
from typing import Tuple
import django.contrib.auth.forms
import django.http as http
import functools
import logging


User = get_user_model()

logger = logging.getLogger('django')


def _get_user_and_profile(request) -> Tuple[User, Profile] | Tuple[User, None]:
    user = request.user
    try:
        profile = user.profile
    except User.profile.RelatedObjectDoesNotExist:
        profile = None

    return (user, profile)


def _validation_errors(request, template_name, form) -> http.HttpResponse:
    error_list = functools.reduce(sum, list(form.errors.values()))
    logging.error('Received invalid form')
    messages.error(request, "\n\n".join(error_list))
    return render(request, template_name, {"form": form})


def _no_profile_error(request) -> http.HttpResponseRedirect:
    message = f'There is no profile for {request.user}'
    logger.error(message)
    messages.error(request, message)
    return http.HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))


def _get_initial_data(user: User, profile: Profile) -> dict:

    if not profile:
        return {}

    # fill form with user data
    initial_data = {}
    for field in UserDataForm().fields:
        if hasattr(profile, field):
            initial_data[field] = getattr(profile, field)
        else:
            assert hasattr(user, field)
            initial_data[field] = getattr(user, field)

    return initial_data


class PrintRegistrationView(generic.View):
    """
    View with the users data.

    The data is not editable and used to automatically fill out the
    registration form.
    """

    template_name = 'registration/print_registration.html'

    def setup(self, request, *args, **kwargs):
        """Initialize attributes."""
        self.user, self.profile = _get_user_and_profile(request)

        return super().setup(request, *args, **kwargs)

    def get(self, request):
        """
        Handle get requests.

        Create a form with the users data.
        """
        if not self.profile:
            return _no_profile_error(request)

        self.initial_data = _get_initial_data(self.user, self.profile)
        form = UserDataForm(self.initial_data)

        return render(
            request,
            self.template_name,
            {'form': form, 'user': self.user}
        )


@method_decorator(login_required, name='dispatch')
class RegistrationFilledFormFile(generic.View):
    """View to deliver a filled registration form."""

    def get(self, request):
        """Handle the get request and return the pdf file."""
        user, profile = _get_user_and_profile(request)

        if not profile:
            return _no_profile_error(request)

        return generate_registration_form(user, profile)


class RegistrationPlainFormFile(generic.View):
    """View to deliver a plain registration form."""

    def get(self, request):
        """Handle the get request and return the pdf file."""
        return http.FileResponse(
            open('files/Nutzerkartei_Anmeldung_2017.pdf', 'rb'),
            filename=('registration_form.pdf')
        )


class EditProfileView(generic.View):
    """View so the user can edit his/her profile."""

    template_name = 'registration/edit_profile.html'

    def setup(self, request, *args, **kwargs):
        """Initialize attributes."""
        self.user, self.profile = _get_user_and_profile(request)
        self.initial_data = _get_initial_data(self.user, self.profile)

        return super().setup(request, *args, **kwargs)

    def get(self, request):
        """
        Handle get requests.

        Create form with user data and writeable fields depending on the users
        verification.
        """
        if not self.profile:
            return _no_profile_error(request)

        form = UserDataForm(self.initial_data)

        ALWAYS_WRITABLE = ['phone_number', 'mobile_number']
        # if verified only ALWAY_WRITABLE fields are writeable
        if self.profile.verified:
            for field in form.fields.keys():
                if field not in ALWAYS_WRITABLE:
                    form.fields[field].widget.attrs['readonly'] = True

        return render(
            request,
            self.template_name,
            {'form': form, 'user': self.user}
        )

    def post(self, request):
        """Submit changes of the users data."""
        assert 'submit' in request.POST
        assert self.profile

        form = UserDataForm(request.POST, initial=self.initial_data)

        if not form.is_valid():
            return _validation_errors(request, self.template_name, form)

        cleaned_data = form.cleaned_data

        for field in form.changed_data:
            if hasattr(self.profile, field):
                setattr(self.profile, field, cleaned_data[field])
            else:
                # It can only be the email
                assert field == 'email'

                # Does the email already belongs to another user?
                email = cleaned_data['email']
                used = User.objects.filter(email=email)
                if used and used[0].id != self.user.id:
                    messages.error(
                        request, f'The e-mail address {email} already exists.')
                    return self.get(request)

                self.user.email = email

            self.initial_data[field] = cleaned_data[field]

        self.user.save()
        self.profile.save()

        messages.success(request, _('Your profile was successfully updated.'))
        return self.get(request)


class RegisterView(generic.CreateView):
    """A view which shows the form to register a user."""

    model = Profile
    form_class = form = ProfileForm
    template_name = 'registration/register.html'

    def post(self, request):
        """Create a new user, if the email address is not used yet."""
        form = self.form(request.POST)

        if not form.is_valid():
            return _validation_errors(request, self.template_name, form)

        data = form.cleaned_data

        user_model = User
        email = data['email'].lower()

        # Does the user already exist?
        if user_model.objects.filter(email=email):
            messages.error(
                request, f'The e-mail address {email} already exists.')
            return render(request, self.template_name, {"form": form})

        user = user_model.objects.create_user(email=email)
        user.save()

        profile = self.model(
            okuser=user,
            first_name=data['first_name'],
            last_name=data['last_name'],
            gender=data['gender'],
            phone_number=data['mobile_number'],
            mobile_number=data['phone_number'],
            birthday=data['birthday'],
            street=data['street'],
            house_number=data['house_number'],
            zipcode=data['zipcode'],
            city=data['city'],
        )
        profile.save()

        send_auth_mail(email)
        messages.success(request, f'Successfully created user {user.email}')
        return redirect('user_created')


class PasswordResetView(auth_views.PasswordResetView):
    """
    Overwrite the get_form_class function.

    Because otherwise get_form_class returns None. The reason for that
    behavior is not known.
    """

    form_class = PasswordResetForm

    extra_email_context = {'ok_name': settings.OK_NAME}

    def get_form_class(self):
        """Return PasswordResetForm explicitly."""
        return self.form_class


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """
    Overwrite the get_form_class function.

    Because otherwise get_form_class returns None. The reason for that
    behavior is not known.
    """

    def get_form_class(self):
        """Return SetPasswordForm explicitly."""
        return django.contrib.auth.forms.SetPasswordForm
