from .forms import RegisterForm
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.views import generic
import functools
import logging


class RegisterView(generic.CreateView):
    """A view which shows the form to register a user."""

    model = get_user_model()
    form_class = RegisterForm  # needed by github workflow
    form = RegisterForm  # needed for local tests
    template_name = 'registration/register.html'

    def post(self, request):
        """Create a new user, if the email address is not used yet."""
        if request.method == 'POST':
            form = RegisterForm(request.POST)

            if not form.is_valid():

                error_list = functools.reduce(sum, list(form.errors.values()))
                logging.error('Received unvalid RegisterForm')
                # TODO send as message
                return HttpResponseBadRequest('Invalid Form:\n\n {}'
                                              .format("\n\n".join(error_list)))

            email = form.cleaned_data['email'].lower()

            user_model = self.model
            new_user = user_model(email=email)
            new_user.save()

            return HttpResponse(f'Successfully created user {new_user}')
