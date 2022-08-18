from . import forms
from .models import LicenseRequest
from .print import generate_license_file
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import generic
from registration.views import _no_profile_error
import django.http as http
import logging


User = get_user_model()
logger = logging.getLogger('django')


def _license_does_not_exist(request) -> http.HttpResponseRedirect:
    message = _('License not found.')
    logger.error(message)
    messages.error(request, message)
    return http.HttpResponseRedirect(
        request.META.get(
            'HTTP_REFERER', reverse_lazy('licenses:licenses')
        )
    )


@method_decorator(login_required, name='dispatch')
class ListLicensesView(generic.list.ListView):
    """List all licenses of the user."""

    template_name = 'licenses/list.html'
    model = LicenseRequest

    def get_queryset(self):
        """List only the licenses of the logged in user."""
        return self.model.objects.filter(okuser=self.request.user)


@method_decorator(login_required, name='dispatch')
class CreateLicenseView(generic.CreateView):
    """Show view to create licenses."""

    model = LicenseRequest
    form_class = form = forms.CreateLicenseRequestForm
    # TODO better success page
    template_name = 'licenses/create.html'

    success_url = reverse_lazy('licenses:licenses')

    def get_form(self, form_class=None):
        """User of created LicenseRequest is current user."""
        form = super().get_form(form_class)
        # TODO check if user has profile
        form.instance.okuser = self.request.user
        return form


@method_decorator(login_required, name='dispatch')
class UpdateLicensesView(generic.edit.UpdateView):
    """Updates a LicenseRequest."""

    form = form_class = forms.CreateLicenseRequestForm
    model = LicenseRequest
    template_name = 'licenses/update.html'
    success_url = reverse_lazy('licenses:licenses')


@method_decorator(login_required, name='dispatch')
class DetailsLicensesView(generic.detail.DetailView):
    """Details of a LicenseRequest."""

    template_name = 'licenses/details.html'
    model = LicenseRequest
    form = form_class = forms.CreateLicenseRequestForm

    def get_context_data(self, **kwargs):
        """Add the LicenseRequestForm to context."""
        context = super().get_context_data(**kwargs)
        context['form'] = forms.CreateLicenseRequestForm(instance=self.object)
        return context


@method_decorator(login_required, name='dispatch')
class FilledLicenseFile(generic.View):
    """View to deliver a filled license document."""

    def get(self, request, pk):
        """Print a license file of the current license request."""
        try:
            license = LicenseRequest.objects.get(pk=pk)
        except LicenseRequest.DoesNotExist:
            return _license_does_not_exist(request)

        if license.okuser != request.user:
            return _license_does_not_exist(request)

        try:
            license.okuser.profile
        except User.profile.RelatedObjectDoesNotExist:
            return _no_profile_error(request)

        return generate_license_file(request.user, license)
