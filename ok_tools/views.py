from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.generic import TemplateView


# Import models from other apps
try:
    from licenses.models import License
except ImportError:
    License = None

try:
    from rental.models import RentalTransaction
except ImportError:
    RentalTransaction = None

try:
    from contributions.models import Contribution
except ImportError:
    Contribution = None

try:
    from projects.models import Project
except ImportError:
    Project = None

try:
    from registration.models import Profile
except ImportError:
    Profile = None

@login_required
def dashboard(request):
    """Dashboard view with statistics and overview for current user"""
    # Get counts for stats cards - only for current user
    if License:
        license_count = License.objects.filter(profile__okuser=request.user).count()
    else:
        license_count = 0

    # Get detailed rental statistics
    try:
        from django.utils import timezone
        from rental.models import RentalRequest
        from rental.models import RentalTransaction

        # Get user's rental requests
        user_rental_requests = RentalRequest.objects.filter(user=request.user)

        # Count active rentals (reserved/issued and not expired)
        active_rentals = user_rental_requests.filter(
            status__in=['reserved', 'issued'],
            requested_end_date__gte=timezone.now()
        ).count()

        # Count returned rentals
        returned_rentals = user_rental_requests.filter(
            status='returned'
        ).count()

        # Count overdue rentals (reserved/issued but end date passed)
        overdue_rentals = user_rental_requests.filter(
            status__in=['reserved', 'issued'],
            requested_end_date__lt=timezone.now()
        ).count()

        # Total rentals
        total_rentals = user_rental_requests.count()

    except Exception as e:
        print(f"Error calculating rental stats: {e}")
        active_rentals = 0
        returned_rentals = 0
        overdue_rentals = 0
        total_rentals = 0

    context = {
        'license_count': license_count,
        'rental_count': total_rentals,
        'contribution_count': Contribution.objects.filter(
            license__profile__okuser=request.user
        ).count() if Contribution else 0,
        'active_rentals': active_rentals,
        'returned_rentals': returned_rentals,
        'overdue_rentals': overdue_rentals,
    }

    # Get recent activities for current user
    recent_activities = get_recent_activities(request)
    context['recent_activities'] = recent_activities
    # Debug: print recent activities to console
    print(f"Recent activities for user {request.user.username}: {recent_activities}")

    # Get notifications for current user
    context['notifications'] = get_notifications(request)

    # Get monthly statistics for chart
    monthly_stats = get_monthly_statistics(request)
    # Ensure monthly_stats is properly formatted for JSON serialization
    if monthly_stats:
        # Convert to JSON-serializable format
        context['monthly_stats'] = monthly_stats
    else:
        context['monthly_stats'] = {
            'labels': [],
            'licenses': [],
            'rentals': [],
            'contributions': []
        }



    # Add profile data for the profile card
    try:
        from registration.models import Profile
        profile = Profile.objects.get(okuser=request.user)
        context['profile'] = profile
    except Profile.DoesNotExist:
        context['profile'] = None

    # Add user display name
    if context['profile']:
        if context['profile'].first_name and context['profile'].last_name:
            context['user_display_name'] = f"{context['profile'].first_name} {context['profile'].last_name}"
        elif context['profile'].first_name:
            context['user_display_name'] = context['profile'].first_name
        elif context['profile'].last_name:
            context['user_display_name'] = context['profile'].last_name
        else:
            context['user_display_name'] = request.user.username
    else:
        context['user_display_name'] = request.user.username

    return render(request, 'dashboard.html', context)

def get_recent_activities(request):
    """Get recent activities for dashboard - only for current user."""
    activities = []

    try:
        # Add user's recent licenses
        if License:
            recent_licenses = License.objects.filter(
                profile__okuser=request.user
            ).order_by('-created_at')[:3]
            for license in recent_licenses:
                activities.append({
                    'description': _('License created: %(title)s') % {'title': license.title},
                    'user': request.user,
                    'created_at': license.created_at if hasattr(license, 'created_at') else timezone.now(),
                    'status': _('Completed') if license.confirmed else _('Pending'),
                    'status_color': 'success' if license.confirmed else 'warning'
                })

        # Add user's recent rental transactions
        if RentalTransaction:
            recent_rentals = RentalTransaction.objects.filter(
                performed_by=request.user
            ).order_by('-performed_at')[:2]
            for rental in recent_rentals:
                activities.append({
                    'description': _('Rental %(type)s for %(item)s') % {
                        'type': rental.get_transaction_type_display(),
                        'item': rental.rental_item or rental.room
                    },
                    'user': request.user,
                    'created_at': rental.performed_at if hasattr(rental, 'performed_at') else timezone.now(),
                    'status': rental.get_transaction_type_display(),
                    'status_color': 'info'
                })

        # Add user's recent contributions
        if Contribution:
            recent_contributions = Contribution.objects.filter(
                license__profile__okuser=request.user
            ).order_by('-broadcast_date')[:2]
            for contribution in recent_contributions:
                activities.append({
                    'description': _('Contribution broadcast: %(title)s') % {'title': contribution.license.title},
                    'user': request.user,
                    'created_at': contribution.broadcast_date,
                    'status': _('Live') if contribution.live else _('Recorded'),
                    'status_color': 'success' if contribution.live else 'secondary'
                })

    except Exception as e:
        print(f"Error getting recent activities: {e}")
        # Return empty list if there's an error
        return []

    # Sort by date and return top 5
    activities.sort(key=lambda x: x['created_at'], reverse=True)
    return activities[:5]

def get_notifications(request):
    """Get system notifications for dashboard - only for current user."""
    notifications = []

    try:
        # Get system notifications from database
        from registration.models import Notification
        system_notifications = Notification.objects.filter(
            is_active=True,
            start_date__lte=timezone.now()
        ).exclude(
            end_date__lt=timezone.now()
        ).order_by('-priority', '-created_at')[:5]

        for notification in system_notifications:
            notifications.append({
                'type': notification.notification_type,
                'icon': notification.icon,
                'message': notification.message
            })

    except Exception as e:
        print(f"Error getting system notifications: {e}")

    # Check for user's unconfirmed licenses
    if License:
        pending_licenses = License.objects.filter(
            profile__okuser=request.user,
            confirmed=False
        )
        if pending_licenses.exists():
            notifications.append({
                'type': 'warning',
                'icon': 'exclamation-triangle',
                'message': _('%(count)d of your license(s) pending approval') % {'count': pending_licenses.count()}
            })

    # Check for user's active rentals
    if RentalTransaction:
        active_rentals = RentalTransaction.objects.filter(
            performed_by=request.user,
            transaction_type='issue'
        ).exclude(
            id__in=RentalTransaction.objects.filter(
                transaction_type='return'
            ).values('rental_item')
        )
        if active_rentals.exists():
            notifications.append({
                'type': 'info',
                'icon': 'clock',
                'message': _('You have %(count)d active rental(s)') % {'count': active_rentals.count()}
            })

        # Check for recent contributions
        if Contribution:
            recent_contributions = Contribution.objects.filter(
                license__profile__okuser=request.user,
                broadcast_date__gte=timezone.now() - timedelta(days=7)
            )
            if recent_contributions.exists():
                notifications.append({
                    'type': 'info',
                    'icon': 'broadcast',
                    'message': _('You have %(count)d contribution(s) this week') % {'count': recent_contributions.count()}
                })

    # Add personalized notification if no other notifications
    if not notifications:
        notifications.append({
            'type': 'success',
            'icon': 'check-circle',
            'message': _('Welcome back, %(name)s!') % {'name': request.user.get_full_name() or request.user.username}
        })

    return notifications

def get_monthly_statistics(request):
    """Get monthly statistics for dashboard chart."""
    stats = {
        'labels': [],
        'licenses': [],
        'rentals': [],
        'contributions': []
    }

    # Get last 6 months
    current_date = timezone.now()
    for i in range(5, -1, -1):
        month_start = current_date.replace(day=1) - timedelta(days=i*30)
        month_end = month_start.replace(day=28) + timedelta(days=4)
        month_end = month_end.replace(day=1) - timedelta(days=1)

        month_label = month_start.strftime('%b')
        stats['labels'].append(month_label)

        # Count licenses for this month
        if License:
            month_licenses = License.objects.filter(
                profile__okuser=request.user,
                created_at__gte=month_start,
                created_at__lte=month_end
            ).count()
        else:
            month_licenses = 0
        stats['licenses'].append(month_licenses)

        # Count rentals for this month
        try:
            from rental.models import RentalRequest
            month_rentals = RentalRequest.objects.filter(
                user=request.user,
                requested_start_date__gte=month_start,
                requested_start_date__lte=month_end
            ).count()
        except Exception as e:
            print(f"Error counting rentals for month {month_label}: {e}")
            month_rentals = 0
        stats['rentals'].append(month_rentals)

        # Count contributions for this month
        if Contribution:
            month_contributions = Contribution.objects.filter(
                license__profile__okuser=request.user,
                broadcast_date__gte=month_start,
                broadcast_date__lte=month_end
            ).count()
        else:
            month_contributions = 0
        stats['contributions'].append(month_contributions)

    # Debug: print stats to console
    print(f"Monthly stats generated: {stats}")
    return stats

def home(request):
    """Home view - redirects to dashboard if authenticated."""
    if request.user.is_authenticated:
        return dashboard(request)
    return render(request, 'home.html')

class RentalDashboardView(LoginRequiredMixin, TemplateView):
    """View for rental dashboard page."""

    template_name = 'rental_dashboard.html'

    def get_context_data(self, **kwargs):
        """Add rental-specific context data."""
        context = super().get_context_data(**kwargs)

        # Import Profile model
        from registration.models import Profile

        # Add user info
        context['user'] = self.request.user

        # Add any additional rental context if needed
        try:
            profile = Profile.objects.get(okuser=self.request.user)
            context['profile'] = profile

            # Get user display name from profile first_name and last_name
            if profile.first_name and profile.last_name:
                context['user_display_name'] = f"{profile.first_name} {profile.last_name}"
            elif profile.first_name:
                context['user_display_name'] = profile.first_name
            elif profile.last_name:
                context['user_display_name'] = profile.last_name
            else:
                # Fallback to user's email or username
                context['user_display_name'] = self.request.user.email or self.request.user.username

        except Profile.DoesNotExist:
            context['profile'] = None
            # Fallback to user's email or username
            context['user_display_name'] = self.request.user.email or self.request.user.username

        # Add user ID for JavaScript API calls
        context['user_id'] = self.request.user.id

        # Add rental statistics for the current user
        try:
            from django.utils import timezone
            from rental.models import RentalRequest

            # Get user's rental requests
            user_rental_requests = RentalRequest.objects.filter(user=self.request.user)

            # Count active rentals (reserved/issued and not expired)
            context['active_rentals'] = user_rental_requests.filter(
                status__in=['reserved', 'issued']
            ).filter(
                requested_end_date__isnull=False,
                requested_end_date__gte=timezone.now()
            ).count()

            # Count returned rentals
            context['returned_rentals'] = user_rental_requests.filter(
                status='returned'
            ).count()

            # Count overdue rentals (reserved/issued but end date passed)
            context['overdue_rentals'] = user_rental_requests.filter(
                status__in=['reserved', 'issued']
            ).filter(
                requested_end_date__isnull=False,
                requested_end_date__lt=timezone.now()
            ).count()

        except Exception as e:
            print(f"Error calculating rental stats for dashboard: {e}")
            context['active_rentals'] = 0
            context['returned_rentals'] = 0
            context['overdue_rentals'] = 0



        return context
