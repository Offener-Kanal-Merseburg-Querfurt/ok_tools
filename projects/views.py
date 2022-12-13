from . import forms
from .models import Project
from .models import ProjectParticipant
from django import http
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic


class FindView(generic.FormView):
    """Find a Project to sign in by its ID."""

    form_class = forms.FindProjectForm
    template_name = 'projects/find.html'

    def form_valid(self, form) -> http.HttpResponse:
        """Redirect to the sign-in view for the given project."""
        return redirect(
            reverse_lazy('projects:sign-in', args=(form.data.get('id'),)))


class SignInView(generic.FormView):
    """View to sign in for a project."""

    model = ProjectParticipant
    form_class = form = forms.AddParticipantForm
    template_name = 'projects/create_participant.html'
    project = None

    def setup(self, request: http.HttpRequest, *args, **kwargs) -> None:
        """Get the project object from its id."""
        try:
            self.project = Project.objects.get(id=kwargs['id'])
        except Project.DoesNotExist:
            # self.project stays None
            pass
        return super().setup(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add the project to the context."""
        context = super().get_context_data(**kwargs)
        context['project'] = self.project
        return context

    def form_valid(self, form) -> http.HttpResponse:
        """Add the participant to the project."""
        data = form.cleaned_data
        participant, created = ProjectParticipant.objects.get_or_create(
            name=data.get('name'),
            age=data.get('age'),
            gender=data.get('gender'),
        )
        if participant not in self.project.participants.all():
            self.project.participants.add(participant.id)
            messages.success(
                self.request,
                _('%(participant)s successfully added.') % {
                    "participant": str(participant)})
        else:
            messages.warning(
                self.request,
                _('%(participant)s is already a participant.') % {
                    "participant": str(participant)})
        return redirect(self.request.path)

    def get(self, request, *args, **kwargs):
        """Return a 404 if no project was found."""
        if not self.project:
            return http.Http404()

        return super().get(request, *args, **kwargs)
