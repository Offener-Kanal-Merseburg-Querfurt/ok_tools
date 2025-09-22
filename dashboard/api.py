from .widgets.filters import DashboardFilters
from .widgets.inventory import InventoryWidget
from .widgets.notifications import NotificationsWidget
from contributions.models import Contribution
from datetime import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from licenses.models import Category
from licenses.models import License
from registration.models import MediaAuthority
from registration.models import Profile


def is_admin(user):
    """Check if user is admin."""
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(is_admin)
def api_users_statistics(request):
    """API endpoint for users statistics."""
    try:
        # Initialize filters
        filters = DashboardFilters(request)

        # Get base queryset
        queryset = Profile.objects.all()

        # Apply filters
        filtered_queryset = filters.apply_filters_to_queryset(queryset, 'profile')

        # Calculate basic statistics
        total_users = filtered_queryset.count()

        # Gender distribution
        male_users = filtered_queryset.filter(gender='m').count()
        female_users = filtered_queryset.filter(gender='f').count()
        diverse_users = filtered_queryset.filter(gender='d').count()

        # Verification and membership
        verified_users = filtered_queryset.filter(verified=True).count()
        member_users = filtered_queryset.filter(member=True).count()


        # Users by media authority
        try:
            users_by_authority = list(filtered_queryset.values(
                'media_authority__name'
            ).annotate(
                count=Count('id')
            ).order_by('-count'))
        except Exception:
            users_by_authority = []

        # Age groups
        age_groups = {
            'under_18': 0,
            '18_25': 0,
            '26_35': 0,
            '36_50': 0,
            'over_50': 0
        }

        try:
            for profile in filtered_queryset:
                if profile.birthday:
                    age = relativedelta(filters.date_range['end_date'], profile.birthday).years
                    if age < 18:
                        age_groups['under_18'] += 1
                    elif age < 26:
                        age_groups['18_25'] += 1
                    elif age < 36:
                        age_groups['26_35'] += 1
                    elif age < 51:
                        age_groups['36_50'] += 1
                    else:
                        age_groups['over_50'] += 1
        except Exception:
            # If there's an error calculating ages, keep default values
            pass

        # Registration trend based on selected period
        try:
            start_date = filters.date_range['start_date']
            end_date = filters.date_range['end_date']
            registration_trend = []

            # Calculate number of days in the period
            days_diff = (end_date - start_date).days

            # For periods longer than 30 days, group by weeks
            if days_diff > 30:
                # Group by weeks
                current_date = start_date
                while current_date <= end_date:
                    week_end = min(current_date + timedelta(days=6), end_date)
                    try:
                        if hasattr(filtered_queryset.model, 'created_at'):
                            count = filtered_queryset.filter(
                                created_at__date__gte=current_date,
                                created_at__date__lte=week_end
                            ).count()
                        else:
                            count = 0
                    except Exception:
                        count = 0

                    registration_trend.append({
                        'date': f"{current_date.strftime('%Y-%m-%d')} - {week_end.strftime('%Y-%m-%d')}",
                        'count': count
                    })

                    current_date = week_end + timedelta(days=1)
            else:
                # For shorter periods, show daily data
                current_date = start_date
                while current_date <= end_date:
                    try:
                        if hasattr(filtered_queryset.model, 'created_at'):
                            count = filtered_queryset.filter(
                                created_at__date=current_date
                            ).count()
                        else:
                            count = 0
                    except Exception:
                        count = 0

                    registration_trend.append({
                        'date': current_date.strftime('%Y-%m-%d'),
                        'count': count
                    })

                    current_date += timedelta(days=1)

        except Exception as e:
            registration_trend = []

        # Member distribution
        member_distribution = {
            'members': member_users,
            'non_members': total_users - member_users
        }

        # Get filters data with error handling
        try:
            filters_data = filters.get_all_data()
        except Exception as e:
            filters_data = {}

        data = {
            'basic_stats': {
                'total_users': total_users,
                'male_users': male_users,
                'female_users': female_users,
                'diverse_users': diverse_users,
                'verified_users': verified_users,
                'member_users': member_users,
            },
            'users_by_authority': users_by_authority,
            'age_groups': age_groups,
            'registration_trend': registration_trend,
            'member_distribution': member_distribution,
            'filters': filters_data,
        }

        return JsonResponse({'success': True, 'data': data})

    except Exception as e:
        import traceback
        print(f"Error in api_users_statistics: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_licenses_statistics(request):
    """API endpoint for licenses statistics."""
    try:
        from .widgets.licenses import LicensesWidget

        # Initialize widget
        widget = LicensesWidget(request)

        # Get all data
        data = widget.get_data()

        return JsonResponse({'success': True, 'data': data})

    except Exception as e:
        import traceback
        print(f"Error in api_licenses_statistics: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_contributions_statistics(request):
    """API endpoint for contributions statistics."""
    try:
        from .widgets.contributions import ContributionsWidget

        # Initialize widget
        widget = ContributionsWidget(request)

        # Get all data
        data = widget.get_data()

        return JsonResponse({'success': True, 'data': data})

    except Exception as e:
        import traceback
        print(f"Error in api_contributions_statistics: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_projects_statistics(request):
    """API endpoint for projects statistics."""
    try:
        from .widgets.projects import ProjectsWidget

        # Initialize widget
        widget = ProjectsWidget(request)

        # Get all data
        data = widget.get_data()

        return JsonResponse({'success': True, 'data': data})

    except Exception as e:
        import traceback
        print(f"Error in api_projects_statistics: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)



@login_required
@user_passes_test(is_admin)
def api_filters_data(request):
    """API endpoint for getting filter options."""
    try:
        # Initialize filters to get context
        filters = DashboardFilters(request)

        # Get real media authorities from database
        try:
            media_authorities = MediaAuthority.objects.all().order_by('name')
            media_authorities_data = [{'name': authority.name} for authority in media_authorities]
        except Exception as e:
            media_authorities_data = []

        # Get gender choices from Profile model
        try:
            gender_choices = list(Profile.Gender.choices)
        except Exception as e:
            gender_choices = [
                ('m', 'Male'),
                ('f', 'Female'),
                ('d', 'Diverse')
            ]

        # Get license categories from Category model
        try:
            from licenses.models import Category
            categories = Category.objects.all().order_by('name')
            category_choices = [{'id': cat.id, 'name': cat.name} for cat in categories]
        except Exception as e:
            category_choices = []

        # Get project categories from ProjectCategory model
        try:
            from projects.models import ProjectCategory
            project_categories = ProjectCategory.objects.all().order_by('name')
            project_category_choices = [{'id': cat.id, 'name': cat.name} for cat in project_categories]
        except Exception as e:
            project_category_choices = []

        # Get target groups from TargetGroup model
        try:
            from projects.models import TargetGroup
            target_groups = TargetGroup.objects.all().order_by('name')
            target_group_choices = [{'id': group.id, 'name': group.name} for group in target_groups]
        except Exception as e:
            target_group_choices = []

        # Get project leaders from ProjectLeader model
        try:
            from projects.models import ProjectLeader
            project_leaders = ProjectLeader.objects.all().order_by('name')
            project_leader_choices = [{'id': leader.id, 'name': leader.name} for leader in project_leaders]
        except Exception as e:
            project_leader_choices = []

        # Age groups
        age_groups = [
            ('under_18', 'Under 18'),
            ('18_25', '18-25'),
            ('26_35', '26-35'),
            ('36_50', '36-50'),
            ('over_50', 'Over 50')
        ]

        # Member and verification choices
        member_choices = [
            ('', 'All Users'),
            ('true', 'Members Only'),
            ('false', 'Non-Members Only')
        ]

        verified_choices = [
            ('', 'All Users'),
            ('true', 'Verified Only'),
            ('false', 'Not Verified')
        ]

        # Date range options
        date_range_options = [
            (7, 'Last 7 days'),
            (30, 'Last 30 days'),
            (90, 'Last 90 days'),
            (365, 'Last year'),
            ('all', 'All Time'),
            ('custom', 'Custom Period')
        ]

        # Inventory-specific data
        try:
            from inventory.models import Category as InventoryCategory
            from inventory.models import Location
            from inventory.models import Organization

            # Organizations (owners)
            organizations = Organization.objects.all().values('id', 'name').order_by('name')
            # Locations
            locations = Location.objects.all().values('id', 'name').order_by('name')

            # Inventory categories (using inventory categories)
            inventory_categories = InventoryCategory.objects.all().values('id', 'name').order_by('name')

        except Exception as e:
            print(f"Error loading inventory data: {e}")
            import traceback
            traceback.print_exc()
            organizations = []
            locations = []
            inventory_categories = []

        response_data = {
            'success': True,
            'data': {
                'context': {
                    'media_authorities': media_authorities_data,
                    'gender_choices': gender_choices,
                    'category_choices': category_choices,
                    'project_categories': project_category_choices,
                    'target_groups': target_group_choices,
                    'project_leaders': project_leader_choices,
                    'age_groups': age_groups,
                    'member_choices': member_choices,
                    'verified_choices': verified_choices,
                    'date_range_options': date_range_options
                },
                'filters': filters.get_all_data()
            },
            # Direct access for inventory widget
            'media_authorities': media_authorities_data,
            'organizations': list(organizations),
            'locations': list(locations),
            'inventory_categories': list(inventory_categories)
        }

        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(f"Error in api_filters_data: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_inventory_statistics(request):
    """API endpoint for inventory and rental statistics."""
    try:
        # Initialize filters
        filters = DashboardFilters(request)

        # Get filter parameters
        filter_params = {}
        if 'days' in request.GET:
            filter_params['days'] = request.GET['days']
        if 'start_date' in request.GET:
            filter_params['start_date'] = request.GET['start_date']
        if 'end_date' in request.GET:
            filter_params['end_date'] = request.GET['end_date']

        # Extended filters
        if 'gender' in request.GET and request.GET['gender'] not in ['', 'undefined', 'null']:
            filter_params['gender'] = request.GET['gender']
        if 'member' in request.GET and request.GET['member'] not in ['', 'undefined', 'null']:
            filter_params['member'] = request.GET['member']
        if 'category' in request.GET and request.GET['category'] not in ['', 'undefined', 'null']:
            filter_params['category'] = request.GET['category']
        if 'owner' in request.GET and request.GET['owner'] not in ['', 'undefined', 'null']:
            filter_params['owner'] = request.GET['owner']
        if 'location' in request.GET and request.GET['location'] not in ['', 'undefined', 'null']:
            filter_params['location'] = request.GET['location']
        if 'status' in request.GET and request.GET['status'] not in ['', 'undefined', 'null']:
            filter_params['status'] = request.GET['status']

        # Initialize inventory widget
        inventory_widget = InventoryWidget(filter_params)

        # Get all data
        data = inventory_widget.get_all_data()

        response_data = {
            'success': True,
            'data': data
        }

        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(f"Error in api_inventory_statistics: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_notifications_statistics(request):
    """API endpoint for notifications statistics"""
    try:
        # Get filters from request
        filters = {}

        # Date filters
        if 'days' in request.GET:
            filters['days'] = request.GET.get('days')
        if 'start_date' in request.GET:
            filters['start_date'] = request.GET.get('start_date')
        if 'end_date' in request.GET:
            filters['end_date'] = request.GET.get('end_date')

        # Notification filters
        if 'notification_type' in request.GET:
            filters['notification_type'] = request.GET.get('notification_type')
        if 'priority' in request.GET:
            filters['priority'] = request.GET.get('priority')
        if 'is_active' in request.GET:
            filters['is_active'] = request.GET.get('is_active')
        if 'created_by' in request.GET:
            filters['created_by'] = request.GET.get('created_by')

        # Create widget and get data
        widget = NotificationsWidget(filters)
        data = widget.get_all_data()

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_funnel_metrics(request):
    """API endpoint for funnel metrics."""
    try:
        from .utils import FunnelTracker
        from datetime import timedelta
        from django.utils import timezone

        # Get date range from request
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        days = request.GET.get('days')

        if days and days != 'all' and days != 'custom':
            # Convert days to date range
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=int(days))
        elif days == 'all':
            # All time - no date filtering
            start_date = None
            end_date = None
        elif days == 'custom':
            # Custom date range - use provided dates
            if start_date:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        elif start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date and not days:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Get additional filters
        filters = {
            'media_authority': request.GET.get('media_authority'),
            'gender': request.GET.get('gender'),
            'age_group': request.GET.get('age_group'),
            'category': request.GET.get('category'),
            'status': request.GET.get('status')
        }

        # Get funnel metrics
        tracker = FunnelTracker()
        metrics = tracker.get_funnel_metrics(start_date, end_date, filters)
        breakdown = tracker.get_stage_breakdown(start_date, end_date, filters)

        return JsonResponse({
            'success': True,
            'data': {
                'metrics': metrics['metrics'],
                'conversion_rates': metrics['conversion_rates'],
                'funnel_data': breakdown
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_funnel_breakdown(request):
    """API endpoint for detailed funnel breakdown."""
    try:
        from .utils import FunnelTracker

        # Get date range from request
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Get stage breakdown
        tracker = FunnelTracker()
        breakdown = tracker.get_stage_breakdown(start_date, end_date)

        return JsonResponse({
            'success': True,
            'data': breakdown
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_funnel_trends(request):
    """API endpoint for funnel trends over time."""
    try:
        from .utils import FunnelTracker

        # Get date range from request
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        days = request.GET.get('days', '30')
        if days == 'all':
            start_date = None
            end_date = None
        elif days == 'custom':
            # Custom date range - use provided dates
            if start_date:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            days = int(days)
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days)

        # Get additional filters
        filters = {
            'media_authority': request.GET.get('media_authority'),
            'gender': request.GET.get('gender'),
            'age_group': request.GET.get('age_group'),
            'category': request.GET.get('category'),
            'status': request.GET.get('status')
        }

        # Get trends data
        tracker = FunnelTracker()
        trends = tracker.get_funnel_trends(start_date, end_date, filters)


        return JsonResponse({
            'success': True,
            'data': trends
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_alerts_list(request):
    """API endpoint for alerts and thresholds."""
    try:
        from .models import AlertThreshold
        from .utils import FunnelTracker
        from .widgets.filters import DashboardFilters

        # Parse filter parameters
        try:
            filter_manager = DashboardFilters(request)
            start_date = filter_manager.date_range['start_date']
            end_date = filter_manager.date_range['end_date']
        except Exception as e:
            # Fallback to default values
            start_date = None
            end_date = None

        # Get current metrics for the selected period
        try:
            funnel_tracker = FunnelTracker()
            current_metrics = funnel_tracker.get_funnel_metrics(start_date, end_date)
        except Exception as e:
            # Fallback to empty metrics
            current_metrics = {
                'registered_profiles': 0,
                'verified_profiles': 0,
                'licenses_created': 0,
                'first_broadcasts': 0,
                'rental_completed': 0,
                'verification_rate': 0.0,
                'license_creation_rate': 0.0,
                'first_broadcast_rate': 0.0,
                'rental_completion_rate': 0.0
            }

        # Get all thresholds
        thresholds = AlertThreshold.objects.filter(
            is_active=True
        ).order_by('name')

        # Calculate current alerts based on thresholds and current metrics
        alerts_data = []
        for threshold in thresholds:
            current_value = 0.0
            alert_triggered = False

            # Get current value based on threshold stage and metric type
            if threshold.stage == 'registered':
                if threshold.metric_type == 'absolute_count':
                    current_value = current_metrics.get('total_registrations', 0)
                elif threshold.metric_type == 'conversion_rate':
                    current_value = 0.0  # No conversion rate for registered stage
            elif threshold.stage == 'verified':
                if threshold.metric_type == 'absolute_count':
                    current_value = current_metrics.get('verified_users', 0)
                elif threshold.metric_type == 'conversion_rate':
                    # Get verification rate from conversion_rates, not metrics
                    conversion_rates = current_metrics.get('conversion_rates', {})
                    current_value = conversion_rates.get('verification_rate', 0.0)
            elif threshold.stage == 'license_created':
                if threshold.metric_type == 'absolute_count':
                    current_value = current_metrics.get('licenses_created', 0)
                elif threshold.metric_type == 'conversion_rate':
                    # Get license creation rate from conversion_rates, not metrics
                    conversion_rates = current_metrics.get('conversion_rates', {})
                    current_value = conversion_rates.get('license_creation_rate', 0.0)
            elif threshold.stage == 'first_broadcast':
                if threshold.metric_type == 'absolute_count':
                    current_value = current_metrics.get('first_broadcasts', 0)
                elif threshold.metric_type == 'conversion_rate':
                    # Get first broadcast rate from conversion_rates, not metrics
                    conversion_rates = current_metrics.get('conversion_rates', {})
                    current_value = conversion_rates.get('first_broadcast_rate', 0.0)
            elif threshold.stage == 'rental_completed':
                if threshold.metric_type == 'absolute_count':
                    current_value = current_metrics.get('completed_rentals', 0)
                elif threshold.metric_type == 'conversion_rate':
                    # Get rental completion rate from conversion_rates, not metrics
                    conversion_rates = current_metrics.get('conversion_rates', {})
                    current_value = conversion_rates.get('rental_completion_rate', 0.0)

            # Check if alert should be triggered
            if threshold.comparison_operator == 'gt':
                alert_triggered = current_value > threshold.threshold_value
            elif threshold.comparison_operator == 'lt':
                alert_triggered = current_value < threshold.threshold_value
            elif threshold.comparison_operator == 'eq':
                alert_triggered = current_value == threshold.threshold_value


            if alert_triggered:
                alerts_data.append({
                    'id': f"dynamic_{threshold.id}",
                    'threshold_name': threshold.name,
                    'stage': threshold.get_stage_display(),
                    'metric_type': threshold.get_metric_type_display(),
                    'current_value': current_value,
                    'threshold_value': threshold.threshold_value,
                    'message': f"{threshold.name} - {threshold.get_stage_display()} {threshold.get_metric_type_display()} is {current_value:.1f} (threshold: {threshold.threshold_value})",
                    'triggered_at': None,  # Dynamic alert
                    'is_resolved': False
                })

        thresholds_data = []
        for threshold in thresholds:
            thresholds_data.append({
                'id': threshold.id,
                'name': threshold.name,
                'stage': threshold.get_stage_display(),
                'metric_type': threshold.get_metric_type_display(),
                'threshold_value': threshold.threshold_value,
                'comparison_operator': threshold.get_comparison_operator_display(),
                'is_active': threshold.is_active
            })

        return JsonResponse({
            'success': True,
            'data': {
                'alerts': alerts_data,
                'thresholds': thresholds_data
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_alerts_resolve(request, alert_id):
    """API endpoint to resolve an alert."""
    try:
        from .models import AlertLog

        alert = AlertLog.objects.get(id=alert_id)
        alert.is_resolved = True
        alert.resolved_at = timezone.now()
        alert.save()

        return JsonResponse({
            'success': True,
            'message': 'Alert resolved successfully'
        })

    except AlertLog.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Alert not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_recent_users(request):
    """API endpoint for recent user activities."""
    try:
        from datetime import timedelta
        from django.utils import timezone

        # Get recent profiles (last 7 days by default)
        days = int(request.GET.get('days', 7))
        since_date = timezone.now() - timedelta(days=days)

        # Get recent profiles
        recent_profiles = Profile.objects.filter(
            created_at__gte=since_date
        ).order_by('-created_at')[:10]

        # Get recent user activities
        activities = []

        # Add newly registered users
        for profile in recent_profiles:
            activities.append({
                'type': 'user_registered',
                'title': f'New user registered: {profile.first_name} {profile.last_name}',
                'user_name': f'{profile.first_name} {profile.last_name}',
                'user_email': profile.okuser.email if profile.okuser else '',
                'timestamp': profile.created_at,
                'icon': 'bi-person-plus',
                'color': 'success'
            })

        # Get recent profile updates (if we had updated_at field)
        # For now, we'll use verified status changes as an example
        recently_verified = Profile.objects.filter(
            verified=True,
            created_at__gte=since_date
        ).order_by('-created_at')[:5]

        for profile in recently_verified:
            activities.append({
                'type': 'profile_verified',
                'title': f'Profile verified: {profile.first_name} {profile.last_name}',
                'user_name': f'{profile.first_name} {profile.last_name}',
                'user_email': profile.okuser.email if profile.okuser else '',
                'timestamp': profile.created_at,
                'icon': 'bi-check-circle',
                'color': 'info'
            })

        # Get recent license activities
        try:
            from licenses.models import License
            recent_licenses = License.objects.filter(
                created_at__gte=since_date
            ).select_related('profile__okuser').order_by('-created_at')[:5]

            for license in recent_licenses:
                activities.append({
                    'type': 'license_created',
                    'title': f'License created: {license.title}',
                    'user_name': f'{license.profile.first_name} {license.profile.last_name}',
                    'user_email': license.profile.okuser.email if license.profile.okuser else '',
                    'timestamp': license.created_at,
                    'icon': 'bi-file-earmark-text',
                    'color': 'primary'
                })
        except ImportError:
            pass

        # Sort all activities by timestamp
        activities.sort(key=lambda x: x['timestamp'], reverse=True)

        # Format timestamps for display
        for activity in activities:
            time_diff = timezone.now() - activity['timestamp']
            if time_diff.days > 0:
                activity['time_ago'] = f"{time_diff.days} day{'s' if time_diff.days > 1 else ''} ago"
            elif time_diff.seconds > 3600:
                hours = time_diff.seconds // 3600
                activity['time_ago'] = f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                minutes = time_diff.seconds // 60
                activity['time_ago'] = f"{minutes} minute{'s' if minutes > 1 else ''} ago"

        return JsonResponse({
            'success': True,
            'data': {
                'activities': activities[:5],  # Limit to 5 most recent
                'total_count': len(activities),
                'period_days': days
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_recent_licenses(request):
    """API endpoint for recent license activities."""
    try:
        from datetime import timedelta
        from django.utils import timezone

        # Get recent licenses (last 7 days by default)
        days = int(request.GET.get('days', 7))
        since_date = timezone.now() - timedelta(days=days)

        # Get recent license activities
        activities = []

        # Get recent licenses
        try:
            from licenses.models import License
            recent_licenses = License.objects.filter(
                created_at__gte=since_date
            ).select_related('profile__okuser').order_by('-created_at')[:10]

            for license in recent_licenses:
                status_color = 'success' if license.confirmed else 'warning'
                status_icon = 'bi-check-circle' if license.confirmed else 'bi-clock'
                status_text = 'confirmed' if license.confirmed else 'pending'

                activities.append({
                    'type': 'license_created',
                    'title': f'License {status_text}: {license.title}',
                    'user_name': f'{license.profile.first_name} {license.profile.last_name}',
                    'user_email': license.profile.okuser.email if license.profile.okuser else '',
                    'timestamp': license.created_at,
                    'icon': status_icon,
                    'color': status_color,
                    'license_id': license.id
                })

        except ImportError:
            # If licenses app is not available, return empty list
            pass

        # Sort all activities by timestamp
        activities.sort(key=lambda x: x['timestamp'], reverse=True)

        # Format timestamps for display
        for activity in activities:
            time_diff = timezone.now() - activity['timestamp']
            if time_diff.days > 0:
                activity['time_ago'] = f"{time_diff.days} day{'s' if time_diff.days > 1 else ''} ago"
            elif time_diff.seconds > 3600:
                hours = time_diff.seconds // 3600
                activity['time_ago'] = f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                minutes = time_diff.seconds // 60
                activity['time_ago'] = f"{minutes} minute{'s' if minutes > 1 else ''} ago"

        return JsonResponse({
            'success': True,
            'data': {
                'activities': activities[:5],  # Limit to 5 most recent
                'total_count': len(activities),
                'period_days': days
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_system_status(request):
    """API endpoint for system status checks."""
    try:
        from django.core.cache import cache
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        from django.core.mail import send_mail
        from django.db import connection
        from django.utils import timezone
        import os

        status_checks = {}

        # Check Database Status
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    status_checks['database'] = {
                        'status': 'healthy',
                        'message': 'Database connection successful',
                        'response_time': '< 1ms'
                    }
                else:
                    status_checks['database'] = {
                        'status': 'error',
                        'message': 'Database query failed',
                        'response_time': 'N/A'
                    }
        except Exception as e:
            status_checks['database'] = {
                'status': 'error',
                'message': f'Database connection failed: {str(e)}',
                'response_time': 'N/A'
            }

        # Check API Services Status
        try:
            # Check if we can perform basic database operations
            Profile.objects.first()
            status_checks['api_services'] = {
                'status': 'healthy',
                'message': 'API services responding',
                'response_time': '< 1ms'
            }
        except Exception as e:
            status_checks['api_services'] = {
                'status': 'error',
                'message': f'API services error: {str(e)}',
                'response_time': 'N/A'
            }

        # Check File Storage Status
        try:
            # Test file storage by checking if we can access the storage
            test_file_path = 'system_status_test.txt'
            test_content = f'System status check at {timezone.now()}'

            # Try to write a test file
            default_storage.save(test_file_path, ContentFile(test_content.encode()))

            # Try to read it back
            if default_storage.exists(test_file_path):
                # Clean up test file
                default_storage.delete(test_file_path)
                status_checks['file_storage'] = {
                    'status': 'healthy',
                    'message': 'File storage accessible',
                    'response_time': '< 10ms'
                }
            else:
                status_checks['file_storage'] = {
                    'status': 'warning',
                    'message': 'File storage partially accessible',
                    'response_time': 'N/A'
                }
        except Exception as e:
            status_checks['file_storage'] = {
                'status': 'error',
                'message': f'File storage error: {str(e)}',
                'response_time': 'N/A'
            }

        # Check Email Service Status
        try:
            # Check email configuration
            from django.conf import settings

            if hasattr(settings, 'EMAIL_BACKEND'):
                if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
                    status_checks['email_service'] = {
                        'status': 'warning',
                        'message': 'Email service in development mode (console backend)',
                        'response_time': 'N/A'
                    }
                else:
                    # Test email configuration without actually sending
                    if (settings.EMAIL_HOST and
                        settings.EMAIL_PORT and
                        settings.EMAIL_HOST_USER):
                        status_checks['email_service'] = {
                            'status': 'healthy',
                            'message': 'Email service configured',
                            'response_time': 'N/A'
                        }
                    else:
                        status_checks['email_service'] = {
                            'status': 'warning',
                            'message': 'Email service not fully configured',
                            'response_time': 'N/A'
                        }
            else:
                status_checks['email_service'] = {
                    'status': 'error',
                    'message': 'Email backend not configured',
                    'response_time': 'N/A'
                }
        except Exception as e:
            status_checks['email_service'] = {
                'status': 'error',
                'message': f'Email service error: {str(e)}',
                'response_time': 'N/A'
            }

        # Calculate overall system health
        healthy_count = sum(1 for check in status_checks.values() if check['status'] == 'healthy')
        warning_count = sum(1 for check in status_checks.values() if check['status'] == 'warning')
        error_count = sum(1 for check in status_checks.values() if check['status'] == 'error')

        if error_count > 0:
            overall_status = 'error'
            overall_message = f'{error_count} service(s) down'
        elif warning_count > 0:
            overall_status = 'warning'
            overall_message = f'{warning_count} service(s) with warnings'
        else:
            overall_status = 'healthy'
            overall_message = 'All systems operational'

        return JsonResponse({
            'success': True,
            'data': {
                'overall_status': overall_status,
                'overall_message': overall_message,
                'checks': status_checks,
                'summary': {
                    'total_services': len(status_checks),
                    'healthy': healthy_count,
                    'warnings': warning_count,
                    'errors': error_count
                },
                'timestamp': timezone.now().isoformat()
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_quick_stats(request):
    """API endpoint for quick statistics overview."""
    try:
        from datetime import timedelta
        from django.utils import timezone

        # Initialize filters
        filters = DashboardFilters(request)

        # Get base querysets
        profiles_queryset = Profile.objects.all()
        filtered_profiles = filters.apply_filters_to_queryset(profiles_queryset, 'profile')

        # Active Users (verified users)
        active_users = filtered_profiles.filter(verified=True).count()

        # Get license statistics
        try:
            from licenses.models import License
            licenses_queryset = License.objects.all()
            filtered_licenses = filters.apply_filters_to_queryset(licenses_queryset, 'license')

            confirmed_licenses = filtered_licenses.filter(confirmed=True).count()
            pending_licenses = filtered_licenses.filter(confirmed=False).count()
        except ImportError:
            confirmed_licenses = 0
            pending_licenses = 0

        # Get contribution statistics
        try:
            from contributions.models import Contribution
            contributions_queryset = Contribution.objects.all()
            filtered_contributions = filters.apply_filters_to_queryset(contributions_queryset, 'contribution')

            live_contributions = filtered_contributions.filter(live=True).count()
        except ImportError:
            live_contributions = 0

        # Calculate changes (placeholder - would need historical data)
        # For now, return 0 for all changes
        changes = {
            'active_users': 0,
            'confirmed_licenses': 0,
            'live_contributions': 0,
            'pending_licenses': 0
        }

        data = {
            'active_users': {
                'value': active_users,
                'change': changes['active_users'],
                'change_type': 'positive' if changes['active_users'] >= 0 else 'negative'
            },
            'confirmed_licenses': {
                'value': confirmed_licenses,
                'change': changes['confirmed_licenses'],
                'change_type': 'positive' if changes['confirmed_licenses'] >= 0 else 'negative'
            },
            'live_contributions': {
                'value': live_contributions,
                'change': changes['live_contributions'],
                'change_type': 'positive' if changes['live_contributions'] >= 0 else 'negative'
            },
            'pending_licenses': {
                'value': pending_licenses,
                'change': changes['pending_licenses'],
                'change_type': 'positive' if changes['pending_licenses'] >= 0 else 'negative'
            }
        }

        return JsonResponse({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_users_detail(request):
    """API endpoint for detailed users data."""
    try:
        filters = DashboardFilters(request)
        queryset = Profile.objects.all()
        filtered_queryset = filters.apply_filters_to_queryset(queryset, 'profile')

        # Apply additional filtering based on type parameter
        type_filter = request.GET.get('type', 'total')
        if type_filter == 'male':
            filtered_queryset = filtered_queryset.filter(gender='m')
        elif type_filter == 'female':
            filtered_queryset = filtered_queryset.filter(gender='f')
        elif type_filter == 'verified':
            filtered_queryset = filtered_queryset.filter(verified=True)
        elif type_filter == 'member':
            filtered_queryset = filtered_queryset.filter(member=True)
        # For 'total' type, no additional filtering needed

        # Pagination
        page = int(request.GET.get('page', 1))
        per_page = 20  # Users per page
        start = (page - 1) * per_page
        end = start + per_page

        # Get total count for pagination
        total_count = filtered_queryset.count()

        # Get detailed user data for current page
        users_data = []
        for profile in filtered_queryset[start:end]:
            # Calculate age from birthday
            age = None
            if profile.birthday:
                from datetime import date
                today = date.today()
                age = today.year - profile.birthday.year - ((today.month, today.day) < (profile.birthday.month, profile.birthday.day))

            users_data.append({
                'id': profile.id,
                'name': f"{profile.first_name} {profile.last_name}".strip(),
                'email': profile.okuser.email if profile.okuser and hasattr(profile.okuser, 'email') else '',
                'gender': profile.get_gender_display(),
                'age': age,
                'verified': profile.verified,
                'member': profile.member,
                'media_authority': profile.media_authority.name if profile.media_authority else '',
                'city': profile.city or '',
                'created_at': profile.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(profile, 'created_at') else None
            })

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_previous = page > 1
        has_next = page < total_pages

        return JsonResponse({
            'success': True,
            'data': {
                'users': users_data,
                'total_count': total_count,
                'displayed_count': len(users_data),
                'pagination': {
                    'current_page': page,
                    'total_pages': total_pages,
                    'per_page': per_page,
                    'has_previous': has_previous,
                    'has_next': has_next,
                    'start_index': start + 1,
                    'end_index': min(start + per_page, total_count)
                }
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_licenses_detail(request):
    """API endpoint for detailed licenses data."""
    try:
        from .widgets.licenses import LicensesWidget

        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 20))
        type_filter = request.GET.get('type', 'total')

        widget = LicensesWidget(request)
        data = widget.get_detailed_data(page=page, per_page=per_page, type_filter=type_filter)

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_contributions_detail(request):
    """API endpoint for detailed contributions data."""
    try:
        from .widgets.contributions import ContributionsWidget

        # Get parameters from request
        contribution_type = request.GET.get('type', 'total')
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 20))

        # Initialize widget
        widget = ContributionsWidget(request)

        # Get detailed contributions based on type with pagination
        data = widget.get_detailed_contributions(contribution_type, page, per_page)

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        import traceback
        print(f"Error in api_contributions_detail: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_projects_detail(request):
    """API endpoint for detailed projects data with pagination and filtering."""
    try:
        from .widgets.projects import ProjectsWidget
        from django.core.paginator import Paginator

        # Get parameters
        project_type = request.GET.get('type', 'total')  # total, participants, average, external, youth_protection, democracy
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 20))

        widget = ProjectsWidget(request)

        # Get detailed projects based on type
        if project_type == 'total':
            # Show all projects
            data = widget.get_detailed_projects()
        elif project_type == 'participants':
            # Show projects with participants > 0
            data = widget.get_detailed_projects_by_participants()
        elif project_type == 'average':
            # Show projects with average participants
            data = widget.get_detailed_projects_by_average_participants()
        elif project_type == 'external':
            # Show external venue projects
            data = widget.get_detailed_projects('external')
        elif project_type == 'youth_protection':
            # Show youth protection projects
            data = widget.get_detailed_projects('youth_protection')
        elif project_type == 'democracy':
            # Show democracy projects
            data = widget.get_detailed_projects('democracy')
        else:
            # Default to all projects
            data = widget.get_detailed_projects()

        # Apply pagination
        paginator = Paginator(data['projects'], per_page)
        page_obj = paginator.get_page(page)

        return JsonResponse({
            'success': True,
            'data': {
                'projects': list(page_obj),
                'total_count': data['total_count'],
                'displayed_count': len(page_obj),
                'current_page': page,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
            }
        })

    except Exception as e:
        import traceback
        print(f"Error in api_projects_detail: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_inventory_detail(request):
    """API endpoint for detailed inventory data."""
    try:
        # Get the type parameter from request
        inventory_type = request.GET.get('type', 'total')

        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 20))

        # Create filters dict from request parameters
        filters_dict = {}
        for key, value in request.GET.items():
            if key not in ['type', 'page', 'per_page'] and value:
                filters_dict[key] = value

        # Initialize widget with filters dict
        widget = InventoryWidget(filters_dict)

        # Get detailed inventory data based on type with pagination
        data = widget.get_detailed_inventory(inventory_type, page, per_page)

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_notifications_detail(request):
    """API endpoint for detailed notifications data."""
    try:
        # Get filters from request
        filters = {}

        # Date filters
        if 'days' in request.GET:
            filters['days'] = request.GET.get('days')
        if 'start_date' in request.GET:
            filters['start_date'] = request.GET.get('start_date')
        if 'end_date' in request.GET:
            filters['end_date'] = request.GET.get('end_date')

        # Notification filters
        if 'notification_type' in request.GET:
            filters['notification_type'] = request.GET.get('notification_type')
        if 'priority' in request.GET:
            filters['priority'] = request.GET.get('priority')
        if 'is_active' in request.GET:
            filters['is_active'] = request.GET.get('is_active')
        if 'created_by' in request.GET:
            filters['created_by'] = request.GET.get('created_by')

        # Get detail type from request
        detail_type = request.GET.get('type', 'total')

        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        # Create widget and get data
        widget = NotificationsWidget(filters)
        data = widget.get_detailed_notifications(detail_type, page, page_size)

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_notifications_toggle(request, notification_id):
    """API endpoint to toggle notification status."""
    try:
        from .models import Notification

        notification = Notification.objects.get(id=notification_id)
        notification.is_read = not notification.is_read
        notification.save()

        return JsonResponse({
            'success': True,
            'is_read': notification.is_read
        })

    except Notification.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Notification not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_funnel_detail(request):
    """API endpoint for funnel detail data."""
    try:
        from .utils import FunnelTracker
        from datetime import timedelta
        from django.utils import timezone

        # Get parameters
        type_filter = request.GET.get('type', 'registrations')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        days = request.GET.get('days')

        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 20))

        # Calculate date range
        if days and days != 'all' and days != 'custom':
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=int(days))
        elif days == 'all':
            start_date = None
            end_date = None
        elif days == 'custom':
            # Custom date range - use provided dates
            if start_date:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        elif start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date and not days:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Get additional filters
        filters = {
            'media_authority': request.GET.get('media_authority'),
            'gender': request.GET.get('gender'),
            'age_group': request.GET.get('age_group'),
            'category': request.GET.get('category'),
            'status': request.GET.get('status')
        }

        # Get data based on type
        tracker = FunnelTracker()

        if type_filter == 'registrations':
            data = tracker.get_registrations_detail(start_date, end_date, filters, page, per_page)
        elif type_filter == 'verified':
            data = tracker.get_verified_detail(start_date, end_date, filters, page, per_page)
        elif type_filter == 'licenses':
            data = tracker.get_licenses_detail(start_date, end_date, filters, page, per_page)
        elif type_filter == 'broadcasts':
            data = tracker.get_broadcasts_detail(start_date, end_date, filters, page, per_page)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid type filter'
            }, status=400)

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
@login_required
@user_passes_test(is_admin)
def api_threshold_update(request, threshold_id):
    """API endpoint for updating a threshold."""
    try:
        from .models import AlertThreshold
        import json

        threshold = AlertThreshold.objects.get(id=threshold_id)
        data = json.loads(request.body)

        # Update threshold fields
        threshold.name = data.get('name', threshold.name)
        threshold.stage = data.get('stage', threshold.stage)
        threshold.metric_type = data.get('metric_type', threshold.metric_type)
        threshold.threshold_value = data.get('threshold_value', threshold.threshold_value)

        # Convert comparison operator from frontend format to model format
        comparison_operator = data.get('comparison_operator', threshold.comparison_operator)
        if comparison_operator == 'greater_than':
            comparison_operator = 'gt'
        elif comparison_operator == 'less_than':
            comparison_operator = 'lt'
        elif comparison_operator == 'equals':
            comparison_operator = 'eq'

        threshold.comparison_operator = comparison_operator
        threshold.is_active = data.get('is_active', threshold.is_active)

        threshold.save()

        return JsonResponse({
            'success': True,
            'message': 'Threshold updated successfully'
        })

    except AlertThreshold.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Threshold not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_admin)
def api_threshold_toggle(request, threshold_id):
    """API endpoint for toggling a threshold active status."""
    try:
        from .models import AlertThreshold

        threshold = AlertThreshold.objects.get(id=threshold_id)
        threshold.is_active = not threshold.is_active
        threshold.save()

        return JsonResponse({
            'success': True,
            'message': f'Threshold {"activated" if threshold.is_active else "deactivated"} successfully',
            'is_active': threshold.is_active
        })

    except AlertThreshold.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Threshold not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
