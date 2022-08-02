from . import forms
from .models import LicenseRequest
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import generic


@method_decorator(login_required, name='dispatch')
class ListLicensesView(generic.View):
    """List all licenses of the user."""

    template_name = 'licenses/list.html'

    def get(self, request):
        """Handle get requests."""
        return render(request, self.template_name, {})


@method_decorator(login_required, name='dispatch')
class CreateLicenseView(generic.CreateView):
    """Show view to create licenses."""

    model = LicenseRequest
    form_class = form = forms.CreateLicenseRequestForm
    # TODO better success page
    template_name = 'licenses/create.html'

    success_url = reverse_lazy('licenses:licenses')

    def form_valid(self, form):
        """User of the created License is the current user."""
        # TODO check if user has profile
        form.instance.okuser = self.request.user
        return super().form_valid(form)
