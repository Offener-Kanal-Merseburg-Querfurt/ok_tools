from .email import send_auth_mail
from .forms import PasswordResetForm
from .forms import ProfileForm
from .forms import UserDataForm
from .models import Profile
from .print import generate_application_form
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.http import HttpResponseServerError
from django.shortcuts import redirect
from django.shortcuts import render
from django.views import generic
import django.contrib.auth.forms
import functools
import logging


User = get_user_model()

logger = logging.getLogger('django')


def user_data_view(request):
    """
    View with the users data.

    The data is editable for the user as long as he/she is not verified yet.
    Phone numbers are always editable.
    """
    # initialize user and profile
    user = request.user
    try:
        profile = Profile.objects.get(okuser=user)
    except Profile.DoesNotExist:
        logger.error(f'User {user} does not exist.')
        # TODO message
        return HttpResponseServerError()

    form = UserDataForm()

    FORM_KEYS = form.fields.keys()
    ALWAYS_WRITABLE = ['phone_number', 'mobile_number']

    # fill form with user data
    initial_data = {}
    for field in FORM_KEYS:
        if hasattr(profile, field):
            initial_data[field] = getattr(profile, field)
        else:
            assert hasattr(user, field)
            initial_data[field] = getattr(user, field)

    form = UserDataForm(initial=initial_data)

    # if verified only ALWAY_WRITABLE fields are writeable
    if profile.verified:
        for field in FORM_KEYS:
            if field not in ALWAYS_WRITABLE:
                form.fields[field].widget.attrs['readonly'] = True

    if request.method == 'GET':
        return render(
            request,
            'registration/user_data.html',
            {'form': form, 'user': user}
        )

    if 'print' in request.POST:
        return generate_application_form(user, profile)


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
            messages.error(request, "\n\n".join(error_list))
            return render(request, self.template_name, {"form": form})

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
