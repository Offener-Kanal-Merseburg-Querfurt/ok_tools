from .forms import FindProjectForm
from django import http
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import generic


class FindView(generic.FormView):
    """Find a Project to sign in by its ID."""

    form_class = FindProjectForm
    template_name = 'projects/find.html'

    def form_valid(self, form) -> http.HttpResponse:
        """Redirect to the sign-in view for the given project."""
        return redirect(
            reverse_lazy('projects:sign-in', args=(form.data.get('id'),)))


class SignInView(generic.View):
    """View to sign in for a project."""

    def get(self, request, id):
        """Return an form do sign in multiple persons for a project."""
        # TODO
        return http.HttpResponse(f'Success! ID: {id}')
