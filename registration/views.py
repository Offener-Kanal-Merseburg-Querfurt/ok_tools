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
from django.utils.translation import gettext_lazy as _
from django.views import generic
import django.contrib.auth.forms
import django.http as http
import functools
import logging


User = get_user_model()

logger = logging.getLogger('django')


def _validation_errors(request, template_name, form) -> http.HttpResponse:
    error_list = functools.reduce(sum, list(form.errors.values()))
    logging.error('Received invalid RegisterForm')
    messages.error(request, "\n\n".join(error_list))
    return render(request, template_name, {"form": form})


def _no_profile_error(request) -> http.HttpResponseRedirect:
    message = f'There is no profile for {request.user}'
    logger.error(message)
    messages.error(request, message)
    return http.HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))


def _initialize_user_form(user, profile, edit=True) -> UserDataForm:

    FORM_KEYS = UserDataForm().fields.keys()
    ALWAYS_WRITABLE = ['phone_number', 'mobile_number']

    # fill form with user data
    initial_data = {}
    for field in FORM_KEYS:
        if hasattr(profile, field):
            initial_data[field] = getattr(profile, field)
        else:
            assert hasattr(user, field)
            initial_data[field] = getattr(user, field)

    form = UserDataForm(initial_data, initial=initial_data)

    # if verified only ALWAY_WRITABLE fields are writeable
    if profile.verified and edit:
        for field in FORM_KEYS:
            if field not in ALWAYS_WRITABLE:
                form.fields[field].widget.attrs['readonly'] = True

    return form


@login_required
def print_registration_view(request):
    """
    View with the users data.

    The data is editable for the user as long as he/she is not verified yet.
    Phone numbers are always editable.
    """
    template_name = 'registration/print_registration.html'
    # initialize user and profile
    user = request.user
    try:
        profile = user.profile
    except User.profile.RelatedObjectDoesNotExist:
        return _no_profile_error(request)

    form = _initialize_user_form(user, profile, edit=False)

    if request.method == 'GET':
        return render(
            request,
            template_name,
            {'form': form, 'user': user}
        )

    if 'print' in request.POST:
        return generate_registration_form(user, profile)
    else:
        assert 'manual-form' in request.POST
        return http.FileResponse(
            open('files/Nutzerkartei_Anmeldung_2017.pdf', 'rb'),
            filename=('application_form.pdf')
        )


@login_required
def edit_profile(request):
    """View so the user can edit his/her profile."""
    user = request.user
    template_name = 'registration/edit_profile.html'

    try:
        profile = user.profile
    except User.profile.RelatedObjectDoesNotExist:
        return _no_profile_error(request)

    form = _initialize_user_form(user, profile)

    if request.method == 'GET':
        return render(
            request,
            template_name,
            {'form': form, 'user': user}
        )
    else:
        assert request.method == 'POST'
        assert 'submit' in request.POST

        form = UserDataForm(request.POST)
        if not form.is_valid():
            return _validation_errors(request, template_name, form)

        cleaned_data = form.cleaned_data
        for field in form.fields.keys():
            if hasattr(profile, field):
                setattr(profile, field, cleaned_data[field])
            else:
                assert hasattr(user, field)
                # It can only be the email
                setattr(user, field, cleaned_data[field].lower())

        user.save()
        profile.save()

        messages.success(request, _('Your profile was successfully updated.'))
        return render(request, template_name, {"form": form})


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
