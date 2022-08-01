from django.contrib.auth.decorators import login_required
from django.shortcuts import render
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
class CreateLicenseView(generic.View):
    """Show view to create licenses."""

    template_name = 'licenses/create.html'

    def get(self, request):
        """Handle get requests."""
        return render(request, self.template_name, {})
