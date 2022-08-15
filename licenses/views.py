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


@method_decorator(login_required, name='dispatch')
class UpdateLicensesView(generic.edit.UpdateView):
    """Updates a LicenseRequest."""

    form = forms.CreateLicenseRequestForm
    model = LicenseRequest
    template_name = 'licenses/update.html'
    success_url = reverse_lazy('licenses:licenses')


@method_decorator(login_required, name='dispatch')
class DetailsLicensesView(generic.detail.DetailView):
    """Details of a LicenseRequest."""

    template_name = 'licenses/details.html'
    model = LicenseRequest
    form = forms.CreateLicenseRequestForm

    def get_context_data(self, **kwargs):
        """Add the LicenseRequestForm to context."""
        context = super().get_context_data(**kwargs)
        context['form'] = forms.CreateLicenseRequestForm(instance=self.object)
        return context
