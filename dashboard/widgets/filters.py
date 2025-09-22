"""
Filters widget for dashboard.
Provides unified filtering system for all dashboard widgets.
"""

from datetime import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from registration.models import Gender
from registration.models import MediaAuthority
from registration.models import Profile


class DashboardFilters:
    """Unified filtering system for dashboard."""

    def __init__(self, request):
        self.request = request
        self.date_range = self._get_date_range()
        self.filters = self._get_filters()
        self.context = self._get_context()

    def _get_date_range(self):
        """Get date range from request parameters."""
        days_param = self.request.GET.get('days', '30')

        if days_param == 'all':
            # All time - use a very old date
            try:
                start_date = datetime(2000, 1, 1).date()
                end_date = datetime.now().date()
                days = (end_date - start_date).days
            except Exception:
                # If there's an error, fallback to 365 days
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=365)
                days = 365
        elif days_param == 'custom':
            # Custom date range
            start_date_str = self.request.GET.get('start_date')
            end_date_str = self.request.GET.get('end_date')

            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    days = (end_date - start_date).days
                except ValueError:
                    # If date parsing fails, fallback to 30 days
                    end_date = datetime.now().date()
                    start_date = end_date - timedelta(days=30)
                    days = 30
            else:
                # Fallback to 30 days if custom dates not provided
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=30)
                days = 30
        else:
            # Standard predefined periods
            try:
                days = int(days_param)
            except ValueError:
                days = 30

            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days)

        return {
            'start_date': start_date,
            'end_date': end_date,
            'days': days,
            'weeks': days // 7,
            'months': days // 30
        }

    def _get_filters(self):
        """Get all filters from request parameters."""
        return {
            'media_authority': self.request.GET.get('media_authority', ''),
            'gender': self.request.GET.get('gender', ''),
            'age_group': self.request.GET.get('age_group', ''),
            'member': self.request.GET.get('member', ''),
            'verified': self.request.GET.get('verified', ''),
            'category': self.request.GET.get('category', ''),
            'status': self.request.GET.get('status', ''),
            'primary': self.request.GET.get('primary', ''),
        }

    def _get_context(self):
        """Get context data for filters."""
        return {
            'media_authorities': MediaAuthority.objects.all().order_by('name'),
            'gender_choices': Gender.choices,
            'age_groups': [
                ('under_18', _('Under 18')),
                ('18_25', _('18-25')),
                ('26_35', _('26-35')),
                ('36_50', _('36-50')),
                ('over_50', _('Over 50')),
            ],
            'member_choices': [
                ('', _('All Users')),
                ('true', _('Members Only')),
                ('false', _('Non-Members Only')),
            ],
            'verified_choices': [
                ('', _('All Users')),
                ('true', _('Verified Only')),
                ('false', _('Not Verified')),
            ],
            'date_range_options': [
                (7, _('Last 7 days')),
                (30, _('Last 30 days')),
                (90, _('Last 90 days')),
                (365, _('Last year')),
                ('all', _('All Time')),
                ('custom', _('Custom Period')),
            ]
        }

    def apply_filters_to_queryset(self, queryset, model_type='profile'):
        """Apply filters to a queryset based on model type."""
        if model_type == 'profile':
            return self._apply_profile_filters(queryset)
        elif model_type == 'license':
            return self._apply_license_filters(queryset)
        elif model_type == 'contribution':
            return self._apply_contribution_filters(queryset)
        elif model_type == 'project':
            return self._apply_project_filters(queryset)
        elif model_type == 'inventory':
            return self._apply_inventory_filters(queryset)

        return queryset

    def _apply_profile_filters(self, queryset):
        """Apply filters to Profile queryset."""
        if self.filters['media_authority']:
            queryset = queryset.filter(media_authority__name=self.filters['media_authority'])

        if self.filters['gender']:
            queryset = queryset.filter(gender=self.filters['gender'])

        if self.filters['member']:
            member_value = self.filters['member'].lower() == 'true'
            queryset = queryset.filter(member=member_value)

        if self.filters['verified']:
            verified_value = self.filters['verified'].lower() == 'true'
            queryset = queryset.filter(verified=verified_value)

        if self.filters['age_group']:
            queryset = self._filter_by_age_group(queryset)

        # Date range filter for created_at - handle case when field doesn't exist
        try:
            # Check if created_at field exists in the model
            if hasattr(queryset.model, 'created_at'):
                queryset = queryset.filter(
                    created_at__date__gte=self.date_range['start_date'],
                    created_at__date__lte=self.date_range['end_date']
                )
        except Exception:
            # If created_at field doesn't exist or filtering fails, skip date filtering
            pass

        return queryset

    def _apply_license_filters(self, queryset):
        """Apply filters to License queryset."""
        if self.filters['media_authority']:
            queryset = queryset.filter(profile__media_authority__name=self.filters['media_authority'])

        if self.filters['category']:
            queryset = queryset.filter(category__id=self.filters['category'])

        if self.filters['status']:
            if self.filters['status'] == 'confirmed':
                queryset = queryset.filter(confirmed=True)
            elif self.filters['status'] == 'pending':
                queryset = queryset.filter(confirmed=False)

        # Date range filter for created_at - handle case when field doesn't exist
        try:
            # Check if created_at field exists in the model
            if hasattr(queryset.model, 'created_at'):
                queryset = queryset.filter(
                    created_at__date__gte=self.date_range['start_date'],
                    created_at__date__lte=self.date_range['end_date']
                )
        except Exception:
            # If created_at field doesn't exist or filtering fails, skip date filtering
            pass

        return queryset

    def _apply_contribution_filters(self, queryset):
        """Apply filters to Contribution queryset."""
        if self.filters['media_authority']:
            queryset = queryset.filter(license__profile__media_authority__name=self.filters['media_authority'])

        if self.filters['status']:
            if self.filters['status'] == 'live':
                queryset = queryset.filter(live=True)
            elif self.filters['status'] == 'recorded':
                queryset = queryset.filter(live=False)

        # Primary filter
        if self.filters['primary']:
            if self.filters['primary'] == 'primary':
                # Filter for primary contributions only
                primary_contributions = []
                for contribution in queryset:
                    if hasattr(contribution, 'is_primary') and contribution.is_primary():
                        primary_contributions.append(contribution.id)
                queryset = queryset.filter(id__in=primary_contributions)
            elif self.filters['primary'] == 'repetition':
                # Filter for repetition contributions only
                repetition_contributions = []
                for contribution in queryset:
                    if hasattr(contribution, 'is_primary') and not contribution.is_primary():
                        repetition_contributions.append(contribution.id)
                queryset = queryset.filter(id__in=repetition_contributions)

        # Date range filter for broadcast_date - handle case when field doesn't exist
        try:
            queryset = queryset.filter(
                broadcast_date__date__gte=self.date_range['start_date'],
                broadcast_date__date__lte=self.date_range['end_date']
            )
        except Exception:
            # If broadcast_date field doesn't exist, skip date filtering
            pass

        return queryset

    def _apply_project_filters(self, queryset):
        """Apply filters to Project queryset."""
        if self.filters['media_authority']:
            queryset = queryset.filter(media_authority__name=self.filters['media_authority'])

        if self.filters['category']:
            queryset = queryset.filter(category__name=self.filters['category'])

        # Date range filter for created_at - handle case when field doesn't exist
        try:
            # Check if created_at field exists in the model
            if hasattr(queryset.model, 'created_at'):
                queryset = queryset.filter(
                    created_at__date__gte=self.date_range['start_date'],
                    created_at__date__lte=self.date_range['end_date']
                )
        except Exception:
            # If created_at field doesn't exist or filtering fails, skip date filtering
            pass

        return queryset

    def _apply_inventory_filters(self, queryset):
        """Apply filters to InventoryItem queryset."""
        if self.filters['category']:
            queryset = queryset.filter(category__name=self.filters['category'])

        if self.filters['status']:
            if self.filters['status'] == 'available':
                queryset = queryset.filter(available_for_rent=True)
            elif self.filters['status'] == 'rented':
                queryset = queryset.filter(available_for_rent=False)

        return queryset

    def _filter_by_age_group(self, queryset):
        """Filter profiles by age group."""
        end_date = self.date_range['end_date']

        if self.filters['age_group'] == 'under_18':
            cutoff_date = end_date - relativedelta(years=18)
            return queryset.filter(birthday__gt=cutoff_date)
        elif self.filters['age_group'] == '18_25':
            start_cutoff = end_date - relativedelta(years=25)
            end_cutoff = end_date - relativedelta(years=18)
            return queryset.filter(birthday__range=[start_cutoff, end_cutoff])
        elif self.filters['age_group'] == '26_35':
            start_cutoff = end_date - relativedelta(years=35)
            end_cutoff = end_date - relativedelta(years=26)
            return queryset.filter(birthday__range=[start_cutoff, end_cutoff])
        elif self.filters['age_group'] == '36_50':
            start_cutoff = end_date - relativedelta(years=50)
            end_cutoff = end_date - relativedelta(years=36)
            return queryset.filter(birthday__range=[start_cutoff, end_cutoff])
        elif self.filters['age_group'] == 'over_50':
            cutoff_date = end_date - relativedelta(years=50)
            return queryset.filter(birthday__lt=cutoff_date)

        return queryset

    def get_filter_summary(self):
        """Get summary of applied filters."""
        summary = []

        if self.filters['media_authority']:
            summary.append(f"Media Authority: {self.filters['media_authority']}")

        if self.filters['gender']:
            gender_label = dict(Profile.Gender.choices).get(self.filters['gender'], self.filters['gender'])
            summary.append(f"Gender: {gender_label}")

        if self.filters['age_group']:
            age_label = dict(self.context['age_groups']).get(self.filters['age_group'], self.filters['age_group'])
            summary.append(f"Age Group: {age_label}")

        if self.filters['member']:
            member_label = dict(self.context['member_choices']).get(self.filters['member'], self.filters['member'])
            summary.append(f"Member Status: {member_label}")

        if self.filters['verified']:
            verified_label = dict(self.context['verified_choices']).get(self.filters['verified'], self.filters['verified'])
            summary.append(f"Verification: {verified_label}")

        if self.filters['category']:
            summary.append(f"Category: {self.filters['category']}")

        if self.filters['status']:
            summary.append(f"Status: {self.filters['status']}")

        # Date range
        summary.append(f"Period: {self.date_range['days']} days")

        return summary

    def get_all_data(self):
        """Get all filter data for API response."""
        return {
            'filters': self.filters,
            'date_range': {
                'start_date': self.date_range['start_date'].isoformat() if self.date_range['start_date'] else None,
                'end_date': self.date_range['end_date'].isoformat() if self.date_range['end_date'] else None,
            },
            'context': {
                'media_authorities': list(self.context['media_authorities'].values('name')),
                'gender_choices': list(self.context['gender_choices']),
                'age_groups': self.context['age_groups'],
                'member_choices': self.context['member_choices'],
                'verified_choices': self.context['verified_choices'],
                'date_range_options': self.context['date_range_options']
            },
            'summary': self.get_filter_summary()
        }
