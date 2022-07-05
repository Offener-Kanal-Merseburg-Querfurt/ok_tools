# from django.contrib.auth import login_required
from .forms import ProfileForm
from .models import Profile
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.views import generic
import functools
import logging


class RegisterView(generic.CreateView):
    """A view which shows the form to register a user."""

    model = Profile
    form_class = form = ProfileForm
    template_name = 'registration/register.html'

    def post(self, request):
        """Create a new user, if the email address is not used yet."""
        if request.method == 'POST':
            form = self.form(request.POST)

            if not form.is_valid():
                error_list = functools.reduce(sum, list(form.errors.values()))
                logging.error('Received unvalid RegisterForm')
                # TODO send as message
                return HttpResponseBadRequest('Invalid Form:\n\n {}'
                                              .format("\n\n".join(error_list)))

            data = form.cleaned_data

            user_model = get_user_model()
            user = user_model(email=data['email'].lower())
            user.save()
            profile = \
                self.model(okuser=user,
                           first_name=data['first_name'].lower(),
                           last_name=data['last_name'].lower(),
                           gender=data['gender'],
                           phone_number=data['mobile_number'],
                           mobile_number=data['phone_number'],
                           birthday=data['birthday'],
                           street=data['street'].lower(),
                           house_number=data['house_number'],
                           zipcode=data['zipcode'],
                           city=data['city'])

            profile.save()
            # return redirect('register_profile', okuser.id)
            return HttpResponse(f'Successfully created user {user.email}')
