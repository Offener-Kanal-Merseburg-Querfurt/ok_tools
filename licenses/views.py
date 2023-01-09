from . import forms
from .generate_file import generate_license_file
from .models import License
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import generic
from registration.views import _no_profile_error
import datetime
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
    model = License

    def get_queryset(self):
        """List only the licenses of the logged in user."""
        try:
            profile = self.request.user.profile
        except User.profile.RelatedObjectDoesNotExist:
            return

        return self.model.objects.filter(profile=profile)


@method_decorator(login_required, name='dispatch')
class CreateLicenseView(generic.CreateView):
    """Show view to create licenses."""

    model = License
    form_class = form = forms.CreateLicenseForm
    # TODO better success page
    template_name = 'licenses/create.html'

    success_url = reverse_lazy('licenses:licenses')

    def get_success_url(self) -> str:
        """Show a message to confirm the creation."""
        messages.success(
            self.request, _('License %(license)s successfully created.') % {
                'license': str(self.object)})

        return super().get_success_url()

    def get_form(self, form_class=None):
        """User of created License is current user."""
        form = super().get_form(form_class)
        form.instance.profile = self.request.user.profile
        return form

    def get(self, request, *args, **kwargs) -> http.HttpResponse:
        """Get handler to create a LR."""
        try:
            self.request.user.profile
        except User.profile.RelatedObjectDoesNotExist:
            return _no_profile_error(request)
        return super().get(request, *args, **kwargs)


@method_decorator(login_required, name='dispatch')
class UpdateLicensesView(generic.edit.UpdateView):
    """Updates a License."""

    form = form_class = forms.CreateLicenseForm
    model = License
    template_name = 'licenses/update.html'
    success_url = reverse_lazy('licenses:licenses')

    def get_success_url(self) -> str:
        """Show a message to confirm the update."""
        messages.success(
            self.request, _('License %(license)s successfully edited.') % {
                'license': self.object}
        )
        return super().get_success_url()

    def post(self, request, *args, **kwargs) -> http.HttpResponse:
        """Show error message for editing confirmed Licenses."""
        license = self.get_object()
        if license.confirmed:
            message = _('The License %(license)s is already confirmed and'
                        ' therefor no longer editable.') % {'license': license}
            logger.error(message)
            messages.error(request, message)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Screen Boards always have a fixed duration."""
        if form.instance.is_screen_board:
            form.instance.duration = datetime.timedelta(
                seconds=settings.SCREEN_BOARD_DURATION)
        return super().form_valid(form)


@method_decorator(login_required, name='dispatch')
class DetailsLicensesView(generic.detail.DetailView):
    """Details of a License."""

    template_name = 'licenses/details.html'
    model = License
    form = form_class = forms.CreateLicenseForm

    def get_context_data(self, **kwargs):
        """Add the LicenseForm to context."""
        context = super().get_context_data(**kwargs)
        context['form'] = forms.CreateLicenseForm(instance=self.object)
        return context


@method_decorator(login_required, name='dispatch')
class FilledLicenseFile(generic.View):
    """View to deliver a filled license document."""

    def get(self, request, pk):
        """Print a license file of the current license."""
        try:
            license = License.objects.get(pk=pk)
        except License.DoesNotExist:
            return _license_does_not_exist(request)

        if (not license.profile.okuser or
                license.profile.okuser != request.user):
            return _license_does_not_exist(request)

        return generate_license_file(license)
