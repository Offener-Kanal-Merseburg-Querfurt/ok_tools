from django.shortcuts import render
from django.views import generic


class ListLicensesView(generic.View):
    """List all licenses of the user."""

    template_name = 'licenses/list.html'

    def get(self, request):
        """Handle get requests."""
        return render(request, self.template_name, {})


class CreateLicenseView(generic.View):
    """Show view to create licenses."""

    template_name = 'licenses/create.html'

    def get(self, request):
        """Handle get requests."""
        return render(request, self.template_name, {})
