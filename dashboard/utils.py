from .models import AlertLog
from .models import AlertThreshold
from .models import FunnelMetrics
from .models import UserJourney
from .models import UserJourneyStage
from contributions.models import Contribution
from datetime import timedelta
from django.db import models
from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.utils import timezone
from licenses.models import License
from registration.models import OKUser
from registration.models import Profile
from rental.models import RentalRequest
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import logging


logger = logging.getLogger(__name__)


class FunnelTracker:
    """Track and analyze user participation funnel."""

    def __init__(self):
        self.stages = UserJourneyStage.choices

    def track_user_stage(self, user: OKUser, stage: str, **kwargs) -> UserJourney:
        """Track a user reaching a specific stage."""
        try:
            journey, created = UserJourney.objects.get_or_create(
                user=user,
                stage=stage,
                defaults={
                    'achieved_at': timezone.now(),
                    **kwargs
                }
            )

            if not created:
                # Update existing record
                journey.achieved_at = timezone.now()
                for key, value in kwargs.items():
                    setattr(journey, key, value)
                journey.save()

            logger.info(f"User {user.email} reached stage {stage}")
            return journey

        except Exception as e:
            logger.error(f"Error tracking user stage: {e}")
            raise

    def get_user_journey(self, user: OKUser) -> List[UserJourney]:
        """Get complete journey for a user."""
        return UserJourney.objects.filter(user=user).order_by('achieved_at')

    def get_funnel_metrics(self, start_date=None, end_date=None, filters=None) -> Dict:
        """Calculate funnel metrics for a date range."""
        # Get all profiles registered in the period (using Profile.created_at)
        if start_date and end_date:
            registered_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time or when no dates specified, get all profiles
            registered_profiles = Profile.objects.all()

        # Apply additional filters
        if filters:
            if filters.get('media_authority'):
                registered_profiles = registered_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                registered_profiles = registered_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                # Calculate age based on birthday
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    registered_profiles = registered_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'verified':
                    registered_profiles = registered_profiles.filter(verified=True)
                elif filters['status'] == 'unverified':
                    registered_profiles = registered_profiles.filter(verified=False)
                elif filters['status'] == 'member':
                    registered_profiles = registered_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    registered_profiles = registered_profiles.filter(member=False)

        total_registrations = registered_profiles.count()

        # Calculate each stage based on real data
        verified_users = registered_profiles.filter(verified=True).count()
        member_users = registered_profiles.filter(member=True).count()

        # Rental requests by users registered in the period (any time)
        rental_requests = RentalRequest.objects.filter(
            user__profile__in=registered_profiles
        ).count()

        # Completed rentals by users registered in the period (any time)
        completed_rentals = RentalRequest.objects.filter(
            user__profile__in=registered_profiles,
            status__in=['returned', 'completed', 'finished']
        ).count()

        # Licenses created by users registered in the period
        if start_date and end_date:
            licenses_query = License.objects.filter(
                profile__in=registered_profiles,
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time, get all licenses by these profiles
            licenses_query = License.objects.filter(profile__in=registered_profiles)

        if filters and filters.get('category'):
            licenses_query = licenses_query.filter(category_id=filters['category'])
        licenses_created = licenses_query.count()

        # Confirmed licenses by users registered in the period
        confirmed_licenses = licenses_query.filter(confirmed=True).count()

        # Contributions created by users registered in the period
        if start_date and end_date:
            contributions_created = Contribution.objects.filter(
                license__profile__in=registered_profiles,
                broadcast_date__date__range=[start_date, end_date]
            ).count()

            # Live contributions by users registered in the period
            live_contributions = Contribution.objects.filter(
                license__profile__in=registered_profiles,
                broadcast_date__date__range=[start_date, end_date],
                live=True
            ).count()
        else:
            # For 'all' time, get all contributions by these profiles
            contributions_created = Contribution.objects.filter(
                license__profile__in=registered_profiles
            ).count()

            # Live contributions by users registered in the period
            live_contributions = Contribution.objects.filter(
                license__profile__in=registered_profiles,
                live=True
            ).count()

        # First broadcasts (users with their first contribution)
        first_broadcasts = self._get_first_broadcasts(registered_profiles, start_date, end_date)

        # Multiple broadcasts (users with more than one contribution)
        multiple_broadcasts = self._get_multiple_broadcasts(registered_profiles, start_date, end_date)

        # Calculate conversion rates
        verification_rate = (verified_users / total_registrations * 100) if total_registrations > 0 else 0
        membership_rate = (member_users / total_registrations * 100) if total_registrations > 0 else 0
        rental_request_rate = (rental_requests / total_registrations * 100) if total_registrations > 0 else 0
        rental_completion_rate = (completed_rentals / rental_requests * 100) if rental_requests > 0 else 0
        license_creation_rate = (licenses_created / total_registrations * 100) if total_registrations > 0 else 0
        license_confirmation_rate = (confirmed_licenses / licenses_created * 100) if licenses_created > 0 else 0
        contribution_creation_rate = (contributions_created / total_registrations * 100) if total_registrations > 0 else 0
        live_contribution_rate = (live_contributions / contributions_created * 100) if contributions_created > 0 else 0
        first_broadcast_rate = (first_broadcasts / total_registrations * 100) if total_registrations > 0 else 0
        multiple_broadcast_rate = (multiple_broadcasts / total_registrations * 100) if total_registrations > 0 else 0

        return {
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            },
            'metrics': {
                'total_registrations': total_registrations,
                'verified_users': verified_users,
                'member_users': member_users,
                'rental_requests': rental_requests,
                'completed_rentals': completed_rentals,
                'licenses_created': licenses_created,
                'confirmed_licenses': confirmed_licenses,
                'contributions_created': contributions_created,
                'live_contributions': live_contributions,
                'first_broadcasts': first_broadcasts,
                'multiple_broadcasts': multiple_broadcasts,
            },
            'conversion_rates': {
                'verification_rate': round(verification_rate, 2),
                'membership_rate': round(membership_rate, 2),
                'rental_request_rate': round(rental_request_rate, 2),
                'rental_completion_rate': round(rental_completion_rate, 2),
                'license_creation_rate': round(license_creation_rate, 2),
                'license_confirmation_rate': round(license_confirmation_rate, 2),
                'contribution_creation_rate': round(contribution_creation_rate, 2),
                'live_contribution_rate': round(live_contribution_rate, 2),
                'first_broadcast_rate': round(first_broadcast_rate, 2),
                'multiple_broadcast_rate': round(multiple_broadcast_rate, 2),
            }
        }

    def _get_first_broadcasts(self, profiles, start_date, end_date) -> int:
        """Get count of licenses with their first broadcast in the period."""
        # Get all contributions by these profiles
        all_contributions = Contribution.objects.filter(
            license__profile__in=profiles
        )

        # Find first broadcast for each license
        first_broadcast_licenses = set()
        license_ids = all_contributions.values_list('license_id', flat=True).distinct()

        for license_id in license_ids:
            first_contribution = all_contributions.filter(
                license_id=license_id
            ).order_by('broadcast_date').first()

            if first_contribution:
                # If no date range specified (days=all), include all first broadcasts
                if not start_date or not end_date:
                    first_broadcast_licenses.add(license_id)
                elif start_date <= first_contribution.broadcast_date.date() <= end_date:
                    first_broadcast_licenses.add(license_id)

        return len(first_broadcast_licenses)

    def _get_multiple_broadcasts(self, profiles, start_date, end_date) -> int:
        """Get count of profiles with multiple broadcasts in the period."""
        multiple_broadcast_profiles = set()

        for profile in profiles:
            # Count profile's contributions in the period
            if start_date and end_date:
                contribution_count = Contribution.objects.filter(
                    license__profile=profile,
                    broadcast_date__date__range=[start_date, end_date]
                ).count()
            else:
                # For 'all' time, count all contributions
                contribution_count = Contribution.objects.filter(
                    license__profile=profile
                ).count()

            if contribution_count > 1:
                multiple_broadcast_profiles.add(profile.id)

        return len(multiple_broadcast_profiles)

    def get_stage_breakdown(self, start_date=None, end_date=None, filters=None) -> Dict:
        """Get detailed breakdown of users at each stage."""
        # Get all profiles registered in the period (using Profile.created_at)
        if start_date and end_date:
            registered_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time or when no dates specified, get all profiles
            registered_profiles = Profile.objects.all()

        # Apply additional filters (same logic as in get_funnel_metrics)
        if filters:
            if filters.get('media_authority'):
                registered_profiles = registered_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                registered_profiles = registered_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    registered_profiles = registered_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'verified':
                    registered_profiles = registered_profiles.filter(verified=True)
                elif filters['status'] == 'unverified':
                    registered_profiles = registered_profiles.filter(verified=False)
                elif filters['status'] == 'member':
                    registered_profiles = registered_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    registered_profiles = registered_profiles.filter(member=False)

        stage_data = {}

        for stage, stage_name in UserJourneyStage.choices:
            if stage == 'registered':
                stage_data[stage] = {
                    'name': stage_name,
                    'count': registered_profiles.count(),
                    'users': list(registered_profiles.values_list('id', flat=True))
                }
            elif stage == 'verified':
                verified = registered_profiles.filter(verified=True)
                stage_data[stage] = {
                    'name': stage_name,
                    'count': verified.count(),
                    'users': list(verified.values_list('id', flat=True))
                }
            elif stage == 'rental_requested':
                # Count users who made rental requests (any time) among those registered in period
                rental_profiles = RentalRequest.objects.filter(
                    user__profile__in=registered_profiles
                ).values_list('user__profile__id', flat=True).distinct()
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(rental_profiles),
                    'users': list(rental_profiles)
                }
            elif stage == 'rental_completed':
                # Count users who completed rentals (any time) among those registered in period
                completed_profiles = RentalRequest.objects.filter(
                    user__profile__in=registered_profiles,
                    status__in=['returned', 'completed', 'finished']
                ).values_list('user__profile__id', flat=True).distinct()
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(completed_profiles),
                    'users': list(completed_profiles)
                }
            elif stage == 'license_created':
                # Count users who created licenses (any time) among those registered in period
                license_profiles = License.objects.filter(
                    profile__in=registered_profiles
                ).values_list('profile_id', flat=True).distinct()
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(license_profiles),
                    'users': list(license_profiles)
                }
            elif stage == 'contribution_created':
                # Count users who created contributions (any time) among those registered in period
                contribution_profiles = Contribution.objects.filter(
                    license__profile__in=registered_profiles
                ).values_list('license__profile_id', flat=True).distinct()
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(contribution_profiles),
                    'users': list(contribution_profiles)
                }
            elif stage == 'first_broadcast':
                first_broadcast_profiles = self._get_first_broadcast_profiles(registered_profiles, start_date, end_date)
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(first_broadcast_profiles),
                    'users': first_broadcast_profiles
                }
            elif stage == 'multiple_broadcasts':
                multiple_broadcast_profiles = self._get_multiple_broadcast_profiles(registered_profiles, start_date, end_date)
                stage_data[stage] = {
                    'name': stage_name,
                    'count': len(multiple_broadcast_profiles),
                    'users': multiple_broadcast_profiles
                }

        return stage_data

    def _get_first_broadcast_profiles(self, profiles, start_date, end_date) -> List[int]:
        """Get list of profile IDs with their first broadcast in the period."""
        first_broadcast_profiles = []

        for profile in profiles:
            first_contribution = Contribution.objects.filter(
                license__profile=profile
            ).order_by('broadcast_date').first()

            if first_contribution and start_date and end_date and start_date <= first_contribution.broadcast_date.date() <= end_date:
                first_broadcast_profiles.append(profile.id)

        return first_broadcast_profiles

    def _get_multiple_broadcast_profiles(self, profiles, start_date, end_date) -> List[int]:
        """Get list of profile IDs with multiple broadcasts in the period."""
        multiple_broadcast_profiles = []

        for profile in profiles:
            contribution_count = Contribution.objects.filter(
                license__profile=profile,
                broadcast_date__date__range=[start_date, end_date]
            ).count()

            if contribution_count > 1:
                multiple_broadcast_profiles.append(profile.id)

        return multiple_broadcast_profiles

    def cache_funnel_metrics(self, date=None) -> FunnelMetrics:
        """Cache funnel metrics for a specific date."""
        if not date:
            date = timezone.now().date()

        metrics_data = self.get_funnel_metrics(date, date)

        funnel_metrics, created = FunnelMetrics.objects.get_or_create(
            date=date,
            defaults={
                'total_registrations': metrics_data['metrics']['total_registrations'],
                'verified_users': metrics_data['metrics']['verified_users'],
                'rental_requests': metrics_data['metrics']['rental_requests'],
                'completed_rentals': metrics_data['metrics']['completed_rentals'],
                'licenses_created': metrics_data['metrics']['licenses_created'],
                'contributions_created': metrics_data['metrics']['contributions_created'],
                'first_broadcasts': metrics_data['metrics']['first_broadcasts'],
                'multiple_broadcasts': metrics_data['metrics']['multiple_broadcasts'],
                'verification_rate': metrics_data['conversion_rates']['verification_rate'],
                'rental_request_rate': metrics_data['conversion_rates']['rental_request_rate'],
                'rental_completion_rate': metrics_data['conversion_rates']['rental_completion_rate'],
                'license_creation_rate': metrics_data['conversion_rates']['license_creation_rate'],
                'contribution_creation_rate': metrics_data['conversion_rates']['contribution_creation_rate'],
                'first_broadcast_rate': metrics_data['conversion_rates']['first_broadcast_rate'],
                'multiple_broadcast_rate': metrics_data['conversion_rates']['multiple_broadcast_rate'],
            }
        )

        if not created:
            # Update existing metrics
            funnel_metrics.total_registrations = metrics_data['metrics']['total_registrations']
            funnel_metrics.verified_users = metrics_data['metrics']['verified_users']
            funnel_metrics.rental_requests = metrics_data['metrics']['rental_requests']
            funnel_metrics.completed_rentals = metrics_data['metrics']['completed_rentals']
            funnel_metrics.licenses_created = metrics_data['metrics']['licenses_created']
            funnel_metrics.contributions_created = metrics_data['metrics']['contributions_created']
            funnel_metrics.first_broadcasts = metrics_data['metrics']['first_broadcasts']
            funnel_metrics.multiple_broadcasts = metrics_data['metrics']['multiple_broadcasts']
            funnel_metrics.verification_rate = metrics_data['conversion_rates']['verification_rate']
            funnel_metrics.rental_request_rate = metrics_data['conversion_rates']['rental_request_rate']
            funnel_metrics.rental_completion_rate = metrics_data['conversion_rates']['rental_completion_rate']
            funnel_metrics.license_creation_rate = metrics_data['conversion_rates']['license_creation_rate']
            funnel_metrics.contribution_creation_rate = metrics_data['conversion_rates']['contribution_creation_rate']
            funnel_metrics.first_broadcast_rate = metrics_data['conversion_rates']['first_broadcast_rate']
            funnel_metrics.multiple_broadcast_rate = metrics_data['conversion_rates']['multiple_broadcast_rate']
            funnel_metrics.save()

        return funnel_metrics

    def get_registrations_detail(self, start_date=None, end_date=None, filters=None, page=1, per_page=20):
        """Get detailed registrations data."""
        # Get registered profiles
        if start_date and end_date:
            registered_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time or when no dates specified, get all profiles
            registered_profiles = Profile.objects.all()

        # Apply filters
        if filters:
            if filters.get('media_authority'):
                registered_profiles = registered_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                registered_profiles = registered_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    registered_profiles = registered_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'verified':
                    registered_profiles = registered_profiles.filter(verified=True)
                elif filters['status'] == 'unverified':
                    registered_profiles = registered_profiles.filter(verified=False)
                elif filters['status'] == 'member':
                    registered_profiles = registered_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    registered_profiles = registered_profiles.filter(member=False)

        # Calculate pagination
        total_count = registered_profiles.count()
        start_index = (page - 1) * per_page
        end_index = start_index + per_page

        # Get paginated data
        paginated_profiles = registered_profiles.select_related('okuser', 'media_authority')[start_index:end_index]

        # Get detailed data
        profiles_data = []
        for profile in paginated_profiles:
            profiles_data.append({
                'id': profile.id,
                'user_email': profile.okuser.email if profile.okuser else '',
                'first_name': profile.first_name or '',
                'last_name': profile.last_name or '',
                'gender': profile.get_gender_display() if profile.gender else '',
                'birthday': profile.birthday.strftime('%Y-%m-%d') if profile.birthday else '',
                'verified': profile.verified,
                'member': profile.member,
                'media_authority': profile.media_authority.name if profile.media_authority else '',
                'created_at': profile.created_at.strftime('%Y-%m-%d %H:%M'),
                'city': profile.city or ''
            })

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_previous = page > 1
        has_next = page < total_pages

        return {
            'total_count': total_count,
            'displayed_count': len(profiles_data),
            'profiles': profiles_data,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'has_previous': has_previous,
                'has_next': has_next,
                'start_index': start_index + 1,
                'end_index': min(end_index, total_count)
            }
        }

    def get_verified_detail(self, start_date=None, end_date=None, filters=None, page=1, per_page=20):
        """Get detailed verified users data."""
        # Get verified profiles
        if start_date and end_date:
            verified_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date],
                verified=True
            )
        else:
            # For 'all' time or when no dates specified, get all verified profiles
            verified_profiles = Profile.objects.filter(verified=True)

        # Apply filters (same logic as registrations)
        if filters:
            if filters.get('media_authority'):
                verified_profiles = verified_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                verified_profiles = verified_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    verified_profiles = verified_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    verified_profiles = verified_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    verified_profiles = verified_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    verified_profiles = verified_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    verified_profiles = verified_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'member':
                    verified_profiles = verified_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    verified_profiles = verified_profiles.filter(member=False)

        # Calculate pagination
        total_count = verified_profiles.count()
        start_index = (page - 1) * per_page
        end_index = start_index + per_page

        # Get paginated data
        paginated_profiles = verified_profiles.select_related('okuser', 'media_authority')[start_index:end_index]

        # Get detailed data
        profiles_data = []
        for profile in paginated_profiles:
            profiles_data.append({
                'id': profile.id,
                'user_email': profile.okuser.email if profile.okuser else '',
                'first_name': profile.first_name or '',
                'last_name': profile.last_name or '',
                'gender': profile.get_gender_display() if profile.gender else '',
                'birthday': profile.birthday.strftime('%Y-%m-%d') if profile.birthday else '',
                'member': profile.member,
                'media_authority': profile.media_authority.name if profile.media_authority else '',
                'created_at': profile.created_at.strftime('%Y-%m-%d %H:%M'),
                'verified_at': profile.verified_at.strftime('%Y-%m-%d %H:%M') if hasattr(profile, 'verified_at') and profile.verified_at else '',
                'city': profile.city or ''
            })

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_previous = page > 1
        has_next = page < total_pages

        return {
            'total_count': total_count,
            'displayed_count': len(profiles_data),
            'profiles': profiles_data,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'has_previous': has_previous,
                'has_next': has_next,
                'start_index': start_index + 1,
                'end_index': min(end_index, total_count)
            }
        }

    def get_licenses_detail(self, start_date=None, end_date=None, filters=None, page=1, per_page=20):
        """Get detailed licenses data."""
        # Get registered profiles first
        if start_date and end_date:
            registered_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time or when no dates specified, get all profiles
            registered_profiles = Profile.objects.all()

        # Apply filters to registered profiles
        if filters:
            if filters.get('media_authority'):
                registered_profiles = registered_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                registered_profiles = registered_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    registered_profiles = registered_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'verified':
                    registered_profiles = registered_profiles.filter(verified=True)
                elif filters['status'] == 'unverified':
                    registered_profiles = registered_profiles.filter(verified=False)
                elif filters['status'] == 'member':
                    registered_profiles = registered_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    registered_profiles = registered_profiles.filter(member=False)

        # Get licenses created by these profiles (only in the selected period)
        licenses_query = License.objects.filter(
            profile__in=registered_profiles,
            created_at__date__range=[start_date, end_date]
        )
        if filters and filters.get('category'):
            licenses_query = licenses_query.filter(category_id=filters['category'])

        # Calculate pagination
        total_count = licenses_query.count()
        start_index = (page - 1) * per_page
        end_index = start_index + per_page

        # Get paginated data
        paginated_licenses = licenses_query.select_related('profile', 'profile__okuser', 'category')[start_index:end_index]

        # Get detailed data
        licenses_data = []
        for license in paginated_licenses:
            licenses_data.append({
                'id': license.number,  # Use number instead of id
                'number': license.number,
                'title': license.title,
                'subtitle': license.subtitle or '',
                'duration': license.duration,
                'profile_name': f"{license.profile.first_name or ''} {license.profile.last_name or ''}".strip(),
                'profile_email': license.profile.okuser.email if license.profile.okuser else '',
                'category': license.category.name if license.category else '',
                'confirmed': license.confirmed,
                'created_at': license.created_at.strftime('%Y-%m-%d %H:%M'),
                'suggested_date': license.suggested_date.strftime('%Y-%m-%d') if license.suggested_date else '',
                'media_authority': license.profile.media_authority.name if license.profile.media_authority else ''
            })

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_previous = page > 1
        has_next = page < total_pages

        return {
            'total_count': total_count,
            'displayed_count': len(licenses_data),
            'licenses': licenses_data,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'has_previous': has_previous,
                'has_next': has_next,
                'start_index': start_index + 1,
                'end_index': min(end_index, total_count)
            }
        }

    def get_broadcasts_detail(self, start_date=None, end_date=None, filters=None, page=1, per_page=20):
        """Get detailed broadcasts data."""
        # Get registered profiles first
        if start_date and end_date:
            registered_profiles = Profile.objects.filter(
                created_at__date__range=[start_date, end_date]
            )
        else:
            # For 'all' time or when no dates specified, get all profiles
            registered_profiles = Profile.objects.all()

        # Apply filters to registered profiles
        if filters:
            if filters.get('media_authority'):
                registered_profiles = registered_profiles.filter(
                    media_authority__name=filters['media_authority']
                )
            if filters.get('gender'):
                registered_profiles = registered_profiles.filter(
                    gender=filters['gender']
                )
            if filters.get('age_group'):
                from datetime import date
                today = date.today()
                if filters['age_group'] == 'under_18':
                    cutoff_date = today.replace(year=today.year - 18)
                    registered_profiles = registered_profiles.filter(birthday__gt=cutoff_date)
                elif filters['age_group'] == '18_25':
                    cutoff_date_18 = today.replace(year=today.year - 18)
                    cutoff_date_25 = today.replace(year=today.year - 25)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_18,
                        birthday__gt=cutoff_date_25
                    )
                elif filters['age_group'] == '26_35':
                    cutoff_date_26 = today.replace(year=today.year - 26)
                    cutoff_date_35 = today.replace(year=today.year - 35)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_26,
                        birthday__gt=cutoff_date_35
                    )
                elif filters['age_group'] == '36_50':
                    cutoff_date_36 = today.replace(year=today.year - 36)
                    cutoff_date_50 = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(
                        birthday__lte=cutoff_date_36,
                        birthday__gt=cutoff_date_50
                    )
                elif filters['age_group'] == 'over_50':
                    cutoff_date = today.replace(year=today.year - 50)
                    registered_profiles = registered_profiles.filter(birthday__lte=cutoff_date)
            if filters.get('status'):
                if filters['status'] == 'verified':
                    registered_profiles = registered_profiles.filter(verified=True)
                elif filters['status'] == 'unverified':
                    registered_profiles = registered_profiles.filter(verified=False)
                elif filters['status'] == 'member':
                    registered_profiles = registered_profiles.filter(member=True)
                elif filters['status'] == 'non_member':
                    registered_profiles = registered_profiles.filter(member=False)

        # Get only FIRST broadcasts (primary contributions) by these profiles
        # First, get all contributions by these profiles
        all_contributions = Contribution.objects.filter(
            license__profile__in=registered_profiles
        )
        if filters and filters.get('category'):
            all_contributions = all_contributions.filter(license__category_id=filters['category'])

        # Find first broadcast for each license
        first_broadcast_contributions = []
        license_ids = all_contributions.values_list('license_id', flat=True).distinct()

        for license_id in license_ids:
            first_contribution = all_contributions.filter(
                license_id=license_id
            ).order_by('broadcast_date').first()

            if first_contribution:
                # If no date range specified (days=all), include all first broadcasts
                if not start_date or not end_date:
                    first_broadcast_contributions.append(first_contribution.id)
                elif start_date <= first_contribution.broadcast_date.date() <= end_date:
                    first_broadcast_contributions.append(first_contribution.id)

        # Filter to only first broadcasts in the period
        contributions_query = Contribution.objects.filter(
            id__in=first_broadcast_contributions
        )

        # Calculate pagination
        total_count = contributions_query.count()
        start_index = (page - 1) * per_page
        end_index = start_index + per_page

        # Get paginated data
        paginated_contributions = contributions_query.select_related('license', 'license__profile', 'license__profile__okuser', 'license__category')[start_index:end_index]

        # Get detailed data
        contributions_data = []
        for contribution in paginated_contributions:
            contributions_data.append({
                'id': contribution.license.number,  # Use license number instead of contribution id
                'title': contribution.license.title,  # Use license title
                'subtitle': contribution.license.subtitle or '',  # Use license subtitle
                'description': f'Broadcast on {contribution.broadcast_date.strftime("%Y-%m-%d %H:%M")} - {"Live" if contribution.live else "Recorded"}' if contribution.broadcast_date else '',
                'profile_name': f"{contribution.license.profile.first_name or ''} {contribution.license.profile.last_name or ''}".strip(),
                'profile_email': contribution.license.profile.okuser.email if contribution.license.profile.okuser else '',
                'license_number': contribution.license.number,
                'license_title': contribution.license.title,
                'category': contribution.license.category.name if contribution.license.category else '',
                'broadcast_date': contribution.broadcast_date.strftime('%Y-%m-%d') if contribution.broadcast_date else '',
                'created_at': contribution.broadcast_date.strftime('%Y-%m-%d %H:%M') if contribution.broadcast_date else '',
                'media_authority': contribution.license.profile.media_authority.name if contribution.license.profile.media_authority else ''
            })

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_previous = page > 1
        has_next = page < total_pages

        return {
            'total_count': total_count,
            'displayed_count': len(contributions_data),
            'contributions': contributions_data,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'has_previous': has_previous,
                'has_next': has_next,
                'start_index': start_index + 1,
                'end_index': min(end_index, total_count)
            }
        }

    def get_funnel_trends(self, start_date, end_date, filters=None):
        """Get funnel trends over time."""
        try:
            # Quick check: are there any data in the database at all?
            total_profiles = Profile.objects.count()
            total_licenses = License.objects.count()
            total_contributions = Contribution.objects.count()

            # Handle 'all' time case
            if not start_date or not end_date:
                # For 'all' time, find the actual date range of data

                # Find earliest and latest dates from actual data
                earliest_profile = Profile.objects.order_by('created_at').first()
                latest_profile = Profile.objects.order_by('-created_at').first()
                earliest_license = License.objects.order_by('created_at').first()
                latest_license = License.objects.order_by('-created_at').first()
                earliest_contribution = Contribution.objects.order_by('broadcast_date').first()
                latest_contribution = Contribution.objects.order_by('-broadcast_date').first()

                # Determine the actual date range
                dates = []
                if earliest_profile:
                    dates.append(earliest_profile.created_at.date())
                if earliest_license:
                    dates.append(earliest_license.created_at.date())
                if earliest_contribution:
                    dates.append(earliest_contribution.broadcast_date.date())
                if latest_profile:
                    dates.append(latest_profile.created_at.date())
                if latest_license:
                    dates.append(latest_license.created_at.date())
                if latest_contribution:
                    dates.append(latest_contribution.broadcast_date.date())

                if dates:
                    start_date = min(dates)
                    end_date = max(dates)
                else:
                    # Fallback to last 2 years if no data
                    end_date = timezone.now().date()
                    start_date = end_date - timedelta(days=730)

            # Calculate number of days
            days_diff = (end_date - start_date).days

            # Debug logging
            logger.info(f"Funnel trends date range: {start_date} to {end_date} ({days_diff} days)")

            # Check if there's any data in the database
            total_profiles = Profile.objects.count()
            total_licenses = License.objects.count()
            total_contributions = Contribution.objects.count()

            # Check data in the date range
            profiles_in_range = Profile.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date).count()
            licenses_in_range = License.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date).count()
            contributions_in_range = Contribution.objects.filter(broadcast_date__date__gte=start_date, broadcast_date__date__lte=end_date).count()

            # Check actual date ranges in the database
            if total_profiles > 0:
                earliest_profile = Profile.objects.order_by('created_at').first()
                latest_profile = Profile.objects.order_by('-created_at').first()

            # For periods longer than 365 days, group by months
            if days_diff > 365:
                # Group by months
                current_date = start_date
                trends_data = {
                    'dates': [],
                    'registrations': [],
                    'verified': [],
                    'licenses': [],
                    'first_broadcasts': []
                }

                while current_date <= end_date:
                    # Calculate month end
                    if current_date.month == 12:
                        month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)

                    month_end = min(month_end, end_date)

                    # Get data for this month
                    month_registrations = Profile.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lte=month_end
                    ).count()

                    month_verified = Profile.objects.filter(
                        verified=True,
                        created_at__date__gte=current_date,
                        created_at__date__lte=month_end
                    ).count()

                    month_licenses = License.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lte=month_end
                    ).count()

                    month_broadcasts = Contribution.objects.filter(
                        broadcast_date__date__gte=current_date,
                        broadcast_date__date__lte=month_end
                    ).count()

                    # Add all periods, even with zero data
                    trends_data['dates'].append(f"{current_date.strftime('%Y-%m')}")
                    trends_data['registrations'].append(month_registrations)
                    trends_data['verified'].append(month_verified)
                    trends_data['licenses'].append(month_licenses)
                    trends_data['first_broadcasts'].append(month_broadcasts)

                    # Move to next month
                    if current_date.month == 12:
                        current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
                    else:
                        current_date = current_date.replace(month=current_date.month + 1, day=1)
            elif days_diff > 90:
                # Group by weeks
                current_date = start_date
                trends_data = {
                    'dates': [],
                    'registrations': [],
                    'verified': [],
                    'licenses': [],
                    'first_broadcasts': []
                }

                while current_date <= end_date:
                    week_end = min(current_date + timedelta(days=6), end_date)

                    # Get data for this week
                    week_registrations = Profile.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lte=week_end
                    ).count()

                    week_verified = Profile.objects.filter(
                        verified=True,
                        created_at__date__gte=current_date,
                        created_at__date__lte=week_end
                    ).count()

                    week_licenses = License.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lte=week_end
                    ).count()

                    week_broadcasts = Contribution.objects.filter(
                        broadcast_date__date__gte=current_date,
                        broadcast_date__date__lte=week_end
                    ).count()

                    # Add all periods, even with zero data
                    trends_data['dates'].append(f"{current_date.strftime('%Y-%m-%d')} - {week_end.strftime('%Y-%m-%d')}")
                    trends_data['registrations'].append(week_registrations)
                    trends_data['verified'].append(week_verified)
                    trends_data['licenses'].append(week_licenses)
                    trends_data['first_broadcasts'].append(week_broadcasts)

                    current_date = week_end + timedelta(days=1)
            else:
                # For shorter periods, show daily data
                current_date = start_date
                trends_data = {
                    'dates': [],
                    'registrations': [],
                    'verified': [],
                    'licenses': [],
                    'first_broadcasts': []
                }

                while current_date <= end_date:
                    # Get data for this day
                    day_registrations = Profile.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lt=current_date + timedelta(days=1)
                    ).count()

                    day_verified = Profile.objects.filter(
                        verified=True,
                        created_at__date__gte=current_date,
                        created_at__date__lt=current_date + timedelta(days=1)
                    ).count()

                    day_licenses = License.objects.filter(
                        created_at__date__gte=current_date,
                        created_at__date__lt=current_date + timedelta(days=1)
                    ).count()

                    day_broadcasts = Contribution.objects.filter(
                        broadcast_date__date__gte=current_date,
                        broadcast_date__date__lt=current_date + timedelta(days=1)
                    ).count()

                    # Debug first few days

                    # Add all days, even with zero data
                    trends_data['dates'].append(current_date.strftime('%Y-%m-%d'))
                    trends_data['registrations'].append(day_registrations)
                    trends_data['verified'].append(day_verified)
                    trends_data['licenses'].append(day_licenses)
                    trends_data['first_broadcasts'].append(day_broadcasts)

                    current_date += timedelta(days=1)

            # Log the final data for debugging
            logger.info(f"Funnel trends data: {len(trends_data['dates'])} periods, registrations: {sum(trends_data['registrations'])}, verified: {sum(trends_data['verified'])}, licenses: {sum(trends_data['licenses'])}, broadcasts: {sum(trends_data['first_broadcasts'])}")

            return trends_data

        except Exception as e:
            logger.error(f"Error getting funnel trends: {e}")
            return {
                'dates': [],
                'registrations': [],
                'verified': [],
                'licenses': [],
                'first_broadcasts': []
            }


class AlertManager:
    """Manage alert thresholds and notifications."""

    def check_thresholds(self, metrics: Dict) -> List[AlertLog]:
        """Check all active thresholds against current metrics."""
        triggered_alerts = []
        active_thresholds = AlertThreshold.objects.filter(is_active=True)

        for threshold in active_thresholds:
            try:
                current_value = self._get_metric_value(metrics, threshold.stage, threshold.metric_type)

                if self._should_trigger_alert(current_value, threshold.threshold_value, threshold.comparison_operator):
                    alert = AlertLog.objects.create(
                        threshold=threshold,
                        current_value=current_value,
                        threshold_value=threshold.threshold_value,
                        message=self._generate_alert_message(threshold, current_value)
                    )
                    triggered_alerts.append(alert)

                    # Send notification
                    self._send_notification(alert)

            except Exception as e:
                logger.error(f"Error checking threshold {threshold.name}: {e}")

        return triggered_alerts

    def _get_metric_value(self, metrics: Dict, stage: str, metric_type: str) -> float:
        """Get the current value for a specific metric."""
        if metric_type == 'conversion_rate':
            rate_key = f"{stage}_rate"
            return metrics['conversion_rates'].get(rate_key, 0.0)
        elif metric_type == 'absolute_count':
            count_key = f"{stage}s"
            return float(metrics['metrics'].get(count_key, 0))
        elif metric_type == 'trend_change':
            # This would require historical data comparison
            # For now, return 0 as placeholder
            return 0.0

        return 0.0

    def _should_trigger_alert(self, current_value: float, threshold_value: float, operator: str) -> bool:
        """Check if alert should be triggered based on comparison."""
        if operator == 'lt':
            return current_value < threshold_value
        elif operator == 'lte':
            return current_value <= threshold_value
        elif operator == 'gt':
            return current_value > threshold_value
        elif operator == 'gte':
            return current_value >= threshold_value
        elif operator == 'eq':
            return current_value == threshold_value

        return False

    def _generate_alert_message(self, threshold: AlertThreshold, current_value: float) -> str:
        """Generate alert message."""
        return f"Alert: {threshold.name} - {threshold.get_stage_display()} {threshold.get_metric_type_display()} is {current_value} (threshold: {threshold.threshold_value})"


    def _send_notification(self, alert: AlertLog):
        """Send notification for triggered alert."""
        # Log the alert for now
        logger.warning(f"ALERT TRIGGERED: {alert.message}")

        # Future enhancements could include:
        # - Email notifications
        # - Dashboard notifications
        # - Slack/Teams integration
