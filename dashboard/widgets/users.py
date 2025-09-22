"""
Users widget for dashboard.
Provides user statistics and analytics.
"""

from .filters import DashboardFilters
from datetime import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Count
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from registration.models import MediaAuthority
from registration.models import Profile


class UsersWidget:
    """Widget for displaying user statistics."""

    def __init__(self, request):
        self.request = request
        self.filters = DashboardFilters(request)

    def get_basic_stats(self):
        """Get basic user statistics."""
        queryset = Profile.objects.all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

        # Calculate statistics
        total_users = filtered_queryset.count()
        male_users = filtered_queryset.filter(gender='m').count()
        female_users = filtered_queryset.filter(gender='f').count()
        diverse_users = filtered_queryset.filter(gender='d').count()
        verified_users = filtered_queryset.filter(verified=True).count()
        member_users = filtered_queryset.filter(member=True).count()


        return {
            'total_users': total_users,
            'male_users': male_users,
            'female_users': female_users,
            'diverse_users': diverse_users,
            'verified_users': verified_users,
            'member_users': member_users,
        }

    def get_users_by_authority(self):
        """Get user count by media authority."""
        try:
            queryset = Profile.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

            return list(filtered_queryset.values('media_authority__name').annotate(
                count=Count('id')
            ).order_by('-count'))
        except Exception:
            # Return empty list if there's an error
            return []

    def get_age_groups(self):
        """Get user count by age groups."""
        try:
            queryset = Profile.objects.exclude(birthday__isnull=True)
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

            # Calculate age groups
            age_groups = {
                'under_18': 0,
                '18_25': 0,
                '26_35': 0,
                '36_50': 0,
                'over_50': 0
            }

            for profile in filtered_queryset:
                if profile.birthday:
                    age = relativedelta(self.filters.date_range['end_date'], profile.birthday).years
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

            return age_groups
        except Exception:
            # Return default values if there's an error
            return {
                'under_18': 0,
                '18_25': 0,
                '26_35': 0,
                '36_50': 0,
                'over_50': 0
            }

    def get_registration_trend(self):
        """Get user registration trend over time."""
        try:
            queryset = Profile.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

            # Get last 7 days trend
            end_date = self.filters.date_range['end_date']
            trend_data = []

            for i in range(7):
                date = end_date - timedelta(days=i)
                try:
                    # Check if created_at field exists in the model
                    if hasattr(filtered_queryset.model, 'created_at'):
                        count = filtered_queryset.filter(
                            created_at__date=date
                        ).count()
                    else:
                        # If created_at field doesn't exist, use 0
                        count = 0
                except Exception:
                    # If there's an error, use 0
                    count = 0

                trend_data.insert(0, {
                    'date': date.strftime('%Y-%m-%d'),
                    'count': count
                })

            return trend_data
        except Exception:
            # Return empty trend if there's an error
            return []

    def get_gender_distribution(self):
        """Get gender distribution."""
        try:
            queryset = Profile.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

            return list(filtered_queryset.values('gender').annotate(
                count=Count('id')
            ).order_by('-count'))
        except Exception:
            # Return empty list if there's an error
            return []

    def get_member_distribution(self):
        """Get member vs non-member distribution."""
        queryset = Profile.objects.all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

        member_count = filtered_queryset.filter(member=True).count()
        non_member_count = filtered_queryset.filter(member=False).count()

        return {
            'members': member_count,
            'non_members': non_member_count
        }

    def get_verification_distribution(self):
        """Get verified vs non-verified distribution."""
        queryset = Profile.objects.all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

        verified_count = filtered_queryset.filter(verified=True).count()
        non_verified_count = filtered_queryset.filter(verified=False).count()

        return {
            'verified': verified_count,
            'not_verified': non_verified_count
        }

    def get_detailed_users(self, gender=None, verified=None, member=None):
        """Get detailed list of users based on filters."""
        from registration.models import Profile

        queryset = Profile.objects.select_related('okuser', 'media_authority').all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'profile')

        # Apply additional filters
        if gender:
            filtered_queryset = filtered_queryset.filter(gender=gender)
        if verified is not None:
            filtered_queryset = filtered_queryset.filter(verified=verified)
        if member is not None:
            filtered_queryset = filtered_queryset.filter(member=member)

        # Get detailed user data
        users_data = []
        for profile in filtered_queryset[:100]:  # Limit to 100 for performance
            user_data = {
                'id': profile.id,
                'name': f"{profile.first_name} {profile.last_name}".strip() or "",
                'email': profile.okuser.email if profile.okuser else "",
                'gender': profile.get_gender_display(),
                'age': self._calculate_age(profile.birthday) if profile.birthday else "",
                'verified': profile.verified,
                'member': profile.member,
                'media_authority': profile.media_authority.name if profile.media_authority else "",
                'created_at': profile.created_at.strftime('%Y-%m-%d') if profile.created_at else "",
                'city': profile.city or "",
                'phone': profile.phone_number or "",
            }
            users_data.append(user_data)

        return {
            'users': users_data,
            'total_count': filtered_queryset.count(),
            'displayed_count': len(users_data)
        }

    def _calculate_age(self, birthday):
        """Calculate age from birthday."""
        if not birthday:
            return "N/A"

        from datetime import date
        today = date.today()
        age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
        return age

    def get_all_data(self):
        """Get all user statistics data."""
        return {
            'basic_stats': self.get_basic_stats(),
            'users_by_authority': list(self.get_users_by_authority()),
            'age_groups': self.get_age_groups(),
            'registration_trend': self.get_registration_trend(),
            'gender_distribution': list(self.get_gender_distribution()),
            'member_distribution': self.get_member_distribution(),
            'verification_distribution': self.get_verification_distribution(),
            'filters': self.filters.get_all_data(),
        }
