from .models import Contribution
from collections import defaultdict
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import generic
from licenses.models import License
from registration.models import Profile


User = get_user_model()


@method_decorator(login_required, name='dispatch')
class ListContributionsView(generic.list.ListView):
    """List all contributions of the user."""

    template_name = 'contributions/list.html'
    model = Contribution

    def get_context_data(self, **kwargs):
        """Group contributions by license for better display."""
        context = super().get_context_data(**kwargs)

        try:
            # Get profile through OKUser -> Profile relationship
            profile = Profile.objects.get(okuser=self.request.user)
        except Profile.DoesNotExist:
            context['grouped_contributions'] = {}
            context['stats'] = {
                'total_licenses': 0,
                'total_contributions': 0,
                'live_count': 0,
                'recorded_count': 0
            }
            return context

        # Get all contributions for user's licenses
        licenses = License.objects.filter(profile=profile)
        grouped_contributions = defaultdict(list)

        # Initialize counters
        total_contributions = 0
        live_count = 0
        recorded_count = 0

        for license in licenses:
            contributions = Contribution.objects.filter(license=license).order_by('-broadcast_date')
            if contributions.exists():
                grouped_contributions[license] = list(contributions)

                # Count contributions and types
                for contribution in contributions:
                    total_contributions += 1
                    if contribution.live:
                        live_count += 1
                    else:
                        recorded_count += 1

        # Sort licenses by latest contribution date
        sorted_groups = sorted(
            grouped_contributions.items(),
            key=lambda x: x[1][0].broadcast_date if x[1] else None,
            reverse=True
        )

        context['grouped_contributions'] = dict(sorted_groups)
        context['stats'] = {
            'total_licenses': len(grouped_contributions),
            'total_contributions': total_contributions,
            'live_count': live_count,
            'recorded_count': recorded_count
        }
        return context

    def get_queryset(self):
        """Return empty queryset since we handle data in get_context_data."""
        return Contribution.objects.none()
