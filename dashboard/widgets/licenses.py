from .filters import DashboardFilters
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Count
from django.db.models import Q
from django.utils import timezone
from licenses.models import License
from registration.models import Profile


class LicensesWidget:
    """Widget for licenses statistics."""

    def __init__(self, request):
        self.request = request
        self.filters = DashboardFilters(request)
        self._cache = {}

    def get_data(self):
        """Get all licenses data."""
        return {
            'basic_stats': self.get_basic_stats(),
            'licenses_by_category': self.get_licenses_by_category(),
            'licenses_by_authority': self.get_licenses_by_authority(),
            'licenses_by_gender': self.get_licenses_by_gender(),
            'licenses_by_age': self.get_licenses_by_age(),
            'licenses_trend': self.get_licenses_trend(),
            'confirmation_rate': self.get_confirmation_rate(),
            'duration_stats': self.get_duration_stats(),
            'youth_protection_stats': self.get_youth_protection_stats(),
            'media_library_stats': self.get_media_library_stats(),
            'exchange_stats': self.get_exchange_stats(),
            'archive_stats': self.get_archive_stats(),
        }

    def get_basic_stats(self):
        """Get basic license statistics."""
        queryset = License.objects.all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

        total_licenses = filtered_queryset.count()
        confirmed_licenses = filtered_queryset.filter(confirmed=True).count()
        pending_licenses = filtered_queryset.filter(confirmed=False).count()

        # Calculate new licenses (in the selected period)
        try:
            if hasattr(filtered_queryset.model, 'created_at'):
                new_licenses = filtered_queryset.count()  # Already filtered by date
            else:
                new_licenses = total_licenses
        except Exception:
            new_licenses = total_licenses

        return {
            'total_licenses': total_licenses,
            'confirmed_licenses': confirmed_licenses,
            'pending_licenses': pending_licenses,
            'new_licenses': new_licenses,
        }

    def get_duration_stats(self):
        """Get duration-related statistics."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            # Filter out screen boards and licenses without duration
            duration_queryset = filtered_queryset.filter(
                is_screen_board=False,
                duration__isnull=False
            ).exclude(duration=timedelta(seconds=0))

            total_with_duration = duration_queryset.count()

            if total_with_duration == 0:
                return {
                    'total_with_duration': 0,
                    'average_duration_minutes': 0,
                    'total_duration_hours': 0,
                    'duration_distribution': {},
                    'longest_duration': 0,
                    'shortest_duration': 0
                }

            # Calculate average duration
            total_seconds = sum(license_obj.duration.total_seconds() for license_obj in duration_queryset)
            average_seconds = total_seconds / total_with_duration
            average_minutes = round(average_seconds / 60, 1)
            total_hours = round(total_seconds / 3600, 1)

            # Find longest and shortest durations
            durations = [license_obj.duration.total_seconds() for license_obj in duration_queryset]
            longest_seconds = max(durations)
            shortest_seconds = min(durations)

            # Duration distribution (in minutes)
            duration_distribution = {
                '0-5 min': 0,
                '5-15 min': 0,
                '15-30 min': 0,
                '30-60 min': 0,
                '60+ min': 0
            }

            for license_obj in duration_queryset:
                minutes = license_obj.duration.total_seconds() / 60
                if minutes <= 5:
                    duration_distribution['0-5 min'] += 1
                elif minutes <= 15:
                    duration_distribution['5-15 min'] += 1
                elif minutes <= 30:
                    duration_distribution['15-30 min'] += 1
                elif minutes <= 60:
                    duration_distribution['30-60 min'] += 1
                else:
                    duration_distribution['60+ min'] += 1

            return {
                'total_with_duration': total_with_duration,
                'average_duration_minutes': average_minutes,
                'total_duration_hours': total_hours,
                'duration_distribution': duration_distribution,
                'longest_duration': round(longest_seconds / 60, 1),
                'shortest_duration': round(shortest_seconds / 60, 1)
            }

        except Exception as e:
            print(f"Error in get_duration_stats: {e}")
            return {
                'total_with_duration': 0,
                'average_duration_minutes': 0,
                'total_duration_hours': 0,
                'duration_distribution': {},
                'longest_duration': 0,
                'shortest_duration': 0
            }

    def get_licenses_by_category(self):
        """Get license count by category."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            # Get category data with both id and name
            category_data = list(filtered_queryset.values('category__id', 'category__name').annotate(
                count=Count('id')
            ).order_by('-count'))

            # Convert to the expected format
            result = []
            for item in category_data:
                if item['category__name']:  # Only include categories with names
                    result.append({
                        'category__name': item['category__name'],
                        'count': item['count']
                    })

            return result
        except Exception as e:
            print(f"Error in get_licenses_by_category: {e}")
            return []

    def get_licenses_by_authority(self):
        """Get license count by media authority."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            # Optimize with select_related
            filtered_queryset = filtered_queryset.select_related(
                'profile__media_authority'
            )

            return list(filtered_queryset.values('profile__media_authority__name').annotate(
                count=Count('id')
            ).order_by('-count'))
        except Exception:
            return []

    def get_licenses_by_gender(self):
        """Get license count by gender."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            return list(filtered_queryset.values('profile__gender').annotate(
                count=Count('id')
            ).order_by('-count'))
        except Exception:
            return []

    def get_licenses_by_age(self):
        """Get license count by age group."""
        queryset = License.objects.all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

        age_groups = {
            'under_18': 0,
            '18_25': 0,
            '26_35': 0,
            '36_50': 0,
            'over_50': 0
        }

        try:
            # Optimize with select_related and only
            optimized_queryset = filtered_queryset.select_related('profile').only(
                'profile__birthday'
            )

            for license_obj in optimized_queryset.iterator(chunk_size=1000):
                if license_obj.profile and license_obj.profile.birthday:
                    age = relativedelta(self.filters.date_range['end_date'], license_obj.profile.birthday).years
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
            pass

        return age_groups

    def get_licenses_trend(self):
        """Get licenses trend over time."""
        try:
            start_date = self.filters.date_range['start_date']
            end_date = self.filters.date_range['end_date']
            licenses_trend = []

            # Calculate number of days in the period
            days_diff = (end_date - start_date).days

            # For periods longer than 30 days, group by weeks
            if days_diff > 30:
                current_date = start_date
                while current_date <= end_date:
                    week_end = min(current_date + timedelta(days=6), end_date)
                    try:
                        count = License.objects.filter(
                            created_at__date__gte=current_date,
                            created_at__date__lte=week_end
                        ).count()
                    except Exception:
                        count = 0

                    licenses_trend.append({
                        'date': f"{current_date.strftime('%Y-%m-%d')} - {week_end.strftime('%Y-%m-%d')}",
                        'count': count
                    })

                    current_date = week_end + timedelta(days=1)
            else:
                # For shorter periods, show daily data
                current_date = start_date
                while current_date <= end_date:
                    try:
                        count = License.objects.filter(
                            created_at__date=current_date
                        ).count()
                    except Exception:
                        count = 0

                    licenses_trend.append({
                        'date': current_date.strftime('%Y-%m-%d'),
                        'count': count
                    })

                    current_date += timedelta(days=1)

        except Exception:
            licenses_trend = []

        return licenses_trend

    def get_confirmation_rate(self):
        """Get license confirmation rate."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            total = filtered_queryset.count()
            confirmed = filtered_queryset.filter(confirmed=True).count()

            if total > 0:
                rate = (confirmed / total) * 100
            else:
                rate = 0

            return {
                'total': total,
                'confirmed': confirmed,
                'rate': round(rate, 2)
            }
        except Exception:
            return {
                'total': 0,
                'confirmed': 0,
                'rate': 0
            }

    def get_youth_protection_stats(self):
        """Get youth protection statistics."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            total_licenses = filtered_queryset.count()

            # Youth protection necessary
            youth_protection_necessary = filtered_queryset.filter(
                youth_protection_necessary=True
            ).count()

            youth_protection_not_necessary = filtered_queryset.filter(
                youth_protection_necessary=False
            ).count()

            youth_protection_unknown = filtered_queryset.filter(
                youth_protection_necessary__isnull=True
            ).count()

            # Youth protection categories
            youth_categories = list(filtered_queryset.values('youth_protection_category').annotate(
                count=Count('id')
            ).order_by('-count'))

            # Calculate percentages
            youth_protection_rate = round((youth_protection_necessary / total_licenses * 100), 1) if total_licenses > 0 else 0

            return {
                'total_licenses': total_licenses,
                'youth_protection_necessary': youth_protection_necessary,
                'youth_protection_not_necessary': youth_protection_not_necessary,
                'youth_protection_unknown': youth_protection_unknown,
                'youth_protection_rate': youth_protection_rate,
                'youth_categories': youth_categories
            }

        except Exception as e:
            print(f"Error in get_youth_protection_stats: {e}")
            return {
                'total_licenses': 0,
                'youth_protection_necessary': 0,
                'youth_protection_not_necessary': 0,
                'youth_protection_unknown': 0,
                'youth_protection_rate': 0,
                'youth_categories': []
            }

    def get_media_library_stats(self):
        """Get media library storage statistics."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            total_licenses = filtered_queryset.count()

            # Store in OK media library
            store_in_library = filtered_queryset.filter(
                store_in_ok_media_library=True
            ).count()

            not_store_in_library = filtered_queryset.filter(
                store_in_ok_media_library=False
            ).count()

            library_unknown = filtered_queryset.filter(
                store_in_ok_media_library__isnull=True
            ).count()

            # Calculate percentage
            library_rate = round((store_in_library / total_licenses * 100), 1) if total_licenses > 0 else 0

            return {
                'total_licenses': total_licenses,
                'store_in_library': store_in_library,
                'not_store_in_library': not_store_in_library,
                'library_unknown': library_unknown,
                'library_rate': library_rate
            }

        except Exception as e:
            print(f"Error in get_media_library_stats: {e}")
            return {
                'total_licenses': 0,
                'store_in_library': 0,
                'not_store_in_library': 0,
                'library_unknown': 0,
                'library_rate': 0
            }

    def get_exchange_stats(self):
        """Get media authority exchange statistics."""
        try:
            queryset = License.objects.all()
            filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

            total_licenses = filtered_queryset.count()

            # Saxony-Anhalt exchange
            saxony_exchange_allowed = filtered_queryset.filter(
                media_authority_exchange_allowed=True
            ).count()

            saxony_exchange_not_allowed = filtered_queryset.filter(
                media_authority_exchange_allowed=False
            ).count()

            saxony_exchange_unknown = filtered_queryset.filter(
                media_authority_exchange_allowed__isnull=True
            ).count()

            # Other states exchange
            other_states_exchange_allowed = filtered_queryset.filter(
                media_authority_exchange_allowed_other_states=True
            ).count()

            other_states_exchange_not_allowed = filtered_queryset.filter(
                media_authority_exchange_allowed_other_states=False
            ).count()

            other_states_exchange_unknown = filtered_queryset.filter(
                media_authority_exchange_allowed_other_states__isnull=True
            ).count()

            # Calculate percentages
            saxony_rate = round((saxony_exchange_allowed / total_licenses * 100), 1) if total_licenses > 0 else 0
            other_states_rate = round((other_states_exchange_allowed / total_licenses * 100), 1) if total_licenses > 0 else 0

            return {
                'total_licenses': total_licenses,
                'saxony_exchange_allowed': saxony_exchange_allowed,
                'saxony_exchange_not_allowed': saxony_exchange_not_allowed,
                'saxony_exchange_unknown': saxony_exchange_unknown,
                'saxony_rate': saxony_rate,
                'other_states_exchange_allowed': other_states_exchange_allowed,
                'other_states_exchange_not_allowed': other_states_exchange_not_allowed,
                'other_states_exchange_unknown': other_states_exchange_unknown,
                'other_states_rate': other_states_rate
            }

        except Exception as e:
            print(f"Error in get_exchange_stats: {e}")
            return {
                'total_licenses': 0,
                'saxony_exchange_allowed': 0,
                'saxony_exchange_not_allowed': 0,
                'saxony_exchange_unknown': 0,
                'saxony_rate': 0,
                'other_states_exchange_allowed': 0,
                'other_states_exchange_not_allowed': 0,
                'other_states_exchange_unknown': 0,
                'other_states_rate': 0
            }

    def get_archive_stats(self):
        """Get archive statistics for licenses - optimized version."""
        # Check cache first
        cache_key = f"archive_stats_{hash(str(self.filters._get_filters()))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            from contributions.models import Contribution
            from datetime import datetime
            from datetime import timedelta
            from django.db.models import Min

            # Define archive threshold (1 year)
            archive_threshold = datetime.now() - timedelta(days=365)

            # Get filtered licenses for total count (licenses that were shown in the period)
            filtered_queryset = self.filters.apply_filters_to_queryset(License.objects.all(), 'license')
            total_licenses = filtered_queryset.count()

            if total_licenses == 0:
                return {
                    'total_licenses': 0,
                    'archive_licenses': 0,
                    'active_licenses': 0,
                    'recent_licenses': 0,
                    'archive_percentage': 0,
                    'active_percentage': 0,
                    'recent_percentage': 0,
                    'archive_threshold_days': 365
                }

            # Get filtered license IDs for counting
            filtered_license_ids = set(filtered_queryset.values_list('id', flat=True))

            # Use SQL to get first broadcast date for each license
            licenses_with_first_broadcast = License.objects.filter(
                id__in=filtered_license_ids
            ).annotate(
                first_broadcast=Min('contribution__broadcast_date')
            ).values('id', 'first_broadcast', 'created_at')

            archive_licenses = 0
            active_licenses = 0
            recent_licenses = 0

            for license_data in licenses_with_first_broadcast:
                first_broadcast = license_data['first_broadcast']
                created_at = license_data['created_at']

                # Use first broadcast date if available, otherwise use creation date
                reference_date = first_broadcast or created_at

                if reference_date:
                    # Handle timezone
                    if reference_date.tzinfo is not None:
                        reference_date = reference_date.replace(tzinfo=None)

                    if reference_date < archive_threshold:
                        archive_licenses += 1
                    else:
                        active_licenses += 1
                else:
                    # No dates available, count as recent
                    recent_licenses += 1

            # Calculate percentages
            if total_licenses > 0:
                archive_percentage = round((archive_licenses / total_licenses) * 100, 1)
                active_percentage = round((active_licenses / total_licenses) * 100, 1)
                recent_percentage = round((recent_licenses / total_licenses) * 100, 1)
            else:
                archive_percentage = 0
                active_percentage = 0
                recent_percentage = 0

            result = {
                'total_licenses': total_licenses,
                'archive_licenses': archive_licenses,
                'active_licenses': active_licenses,
                'recent_licenses': recent_licenses,
                'archive_percentage': archive_percentage,
                'active_percentage': active_percentage,
                'recent_percentage': recent_percentage,
                'archive_threshold_days': 365
            }

            # Cache the result
            self._cache[cache_key] = result
            return result

        except Exception as e:
            print(f"Error in get_archive_stats: {e}")
            return {
                'total_licenses': 0,
                'archive_licenses': 0,
                'active_licenses': 0,
                'recent_licenses': 0,
                'archive_percentage': 0,
                'active_percentage': 0,
                'recent_percentage': 0,
                'archive_threshold_days': 365
            }

    def get_detailed_licenses(self, status=None, page=1, per_page=20):
        """Get detailed list of licenses based on filters with pagination."""
        from licenses.models import License

        queryset = License.objects.select_related('profile__okuser', 'profile__media_authority', 'category').all()
        filtered_queryset = self.filters.apply_filters_to_queryset(queryset, 'license')

        # Apply additional filters based on status/type
        if status == 'active':
            # Active licenses (confirmed and not expired)
            from django.utils import timezone
            filtered_queryset = filtered_queryset.filter(
                confirmed=True,
                suggested_date__gt=timezone.now()
            )
        elif status == 'expired':
            # Expired licenses (confirmed but expired)
            from django.utils import timezone
            filtered_queryset = filtered_queryset.filter(
                confirmed=True,
                suggested_date__lte=timezone.now()
            )
        elif status == 'pending':
            # Pending licenses (not yet confirmed)
            filtered_queryset = filtered_queryset.filter(confirmed=False)
        elif status == 'total':
            # All licenses (no additional filter)
            pass
        elif status == 'new':
            # New licenses (in the selected period - already filtered by date range)
            pass

        # Calculate pagination
        total_count = filtered_queryset.count()
        start_index = (page - 1) * per_page
        end_index = start_index + per_page

        # Get paginated data
        paginated_queryset = filtered_queryset[start_index:end_index]

        # Get detailed license data
        licenses_data = []
        for license_obj in paginated_queryset:
            license_data = {
                'id': license_obj.id,
                'number': license_obj.number or "",
                'title': license_obj.title or "",
                'subtitle': license_obj.subtitle or "",
                'duration': str(license_obj.duration) if license_obj.duration else "",
                'name': f"{license_obj.profile.first_name} {license_obj.profile.last_name}".strip() if license_obj.profile else "",
                'email': license_obj.profile.okuser.email if license_obj.profile and license_obj.profile.okuser else "",
                'category': license_obj.category.name if license_obj.category else "",
                'created_at': license_obj.created_at.strftime('%Y-%m-%d') if license_obj.created_at else "",
                'confirmed': license_obj.confirmed,
                'media_authority': license_obj.profile.media_authority.name if license_obj.profile and license_obj.profile.media_authority else "",
                'city': license_obj.profile.city if license_obj.profile else "",
            }
            licenses_data.append(license_data)

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_next = page < total_pages
        has_previous = page > 1

        return {
            'licenses': licenses_data,
            'total_count': total_count,
            'displayed_count': len(licenses_data),
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_previous': has_previous,
                'start_index': start_index + 1,
                'end_index': start_index + len(licenses_data)
            }
        }

    def _get_license_status(self, license_obj):
        """Get license status based on dates and confirmation."""
        from django.utils import timezone

        if not license_obj.confirmed:
            return "Pending"

        if license_obj.suggested_date:
            if license_obj.suggested_date <= timezone.now():
                return "Expired"
            else:
                return "Active"

        return "Active"

    def get_detailed_data(self, page=1, per_page=20, type_filter='total'):
        """Get detailed data for the licenses widget."""
        detailed_licenses = self.get_detailed_licenses(status=type_filter, page=page, per_page=per_page)
        return {
            'licenses': detailed_licenses.get('licenses', []),
            'total_count': detailed_licenses.get('total_count', 0),
            'displayed_count': detailed_licenses.get('displayed_count', 0),
            'pagination': detailed_licenses.get('pagination', {}),
            'basic_stats': self.get_basic_stats(),
            'licenses_by_category': self.get_licenses_by_category(),
            'licenses_by_authority': self.get_licenses_by_authority(),
            'licenses_by_gender': self.get_licenses_by_gender(),
            'licenses_by_age': self.get_licenses_by_age(),
            'licenses_trend': self.get_licenses_trend(),
            'confirmation_rate': self.get_confirmation_rate(),
            'duration_stats': self.get_duration_stats(),
            'youth_protection_stats': self.get_youth_protection_stats(),
            'media_library_stats': self.get_media_library_stats(),
            'exchange_stats': self.get_exchange_stats(),
            'archive_stats': self.get_archive_stats(),
        }
