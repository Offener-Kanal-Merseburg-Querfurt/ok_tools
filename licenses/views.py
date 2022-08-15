from . import forms
from .models import LicenseRequest
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import generic


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
