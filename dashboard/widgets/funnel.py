from ..utils import AlertManager
from ..utils import FunnelTracker
from contributions.models import Contribution
from datetime import timedelta
from django.db.models import Count
from django.db.models import Q
from django.utils import timezone
from licenses.models import License
from registration.models import OKUser
from registration.models import Profile
from rental.models import RentalRequest
from typing import Dict
from typing import List
from typing import Optional
import logging


logger = logging.getLogger(__name__)


class FunnelWidget:
    """Widget for user participation funnel analysis."""

    def __init__(self, filters=None):
        self.filters = filters or {}
        self._cache = {}

    def get_funnel_overview(self):
        """Get overview of the participation funnel."""
        cache_key = f"funnel_overview_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        tracker = FunnelTracker()

        # Get date range
        start_date, end_date = self._get_date_range()

        # Get funnel metrics
        metrics = tracker.get_funnel_metrics(start_date, end_date)

        # Get stage breakdown
        breakdown = tracker.get_stage_breakdown(start_date, end_date)

        result = {
            'metrics': metrics,
            'breakdown': breakdown,
            'funnel_data': self._format_funnel_data(breakdown),
            'conversion_analysis': self._analyze_conversions(metrics)
        }

        self._cache[cache_key] = result
        return result

    def get_funnel_trends(self):
        """Get funnel trends over time."""
        cache_key = f"funnel_trends_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        tracker = FunnelTracker()

        # Get date range
        start_date, end_date = self._get_date_range()

        # Get trends data
        trends = self._get_trends_data(start_date, end_date)

        result = {
            'trends': trends,
            'period': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            }
        }

        self._cache[cache_key] = result
        return result

    def get_alerts_summary(self):
        """Get summary of active alerts."""
        cache_key = f"alerts_summary_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        from ..models import AlertLog
        from ..models import AlertThreshold

        # Get active alerts
        active_alerts = AlertLog.objects.filter(
            is_resolved=False
        ).order_by('-triggered_at')[:10]

        # Get alert statistics
        total_alerts = AlertLog.objects.count()
        resolved_alerts = AlertLog.objects.filter(is_resolved=True).count()
        active_count = active_alerts.count()

        # Get threshold statistics
        total_thresholds = AlertThreshold.objects.count()
        active_thresholds = AlertThreshold.objects.filter(is_active=True).count()

        result = {
            'active_alerts': [
                {
                    'id': alert.id,
                    'threshold_name': alert.threshold.name,
                    'stage': alert.threshold.get_stage_display(),
                    'current_value': alert.current_value,
                    'threshold_value': alert.threshold_value,
                    'message': alert.message,
                    'triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None
                }
                for alert in active_alerts
            ],
            'statistics': {
                'total_alerts': total_alerts,
                'resolved_alerts': resolved_alerts,
                'active_alerts': active_count,
                'total_thresholds': total_thresholds,
                'active_thresholds': active_thresholds
            }
        }

        self._cache[cache_key] = result
        return result

    def _get_date_range(self):
        """Get date range from filters."""
        if 'days' in self.filters and self.filters['days']:
            if self.filters['days'] == 'custom':
                start_date = self.filters.get('start_date')
                end_date = self.filters.get('end_date')
                if start_date:
                    start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
                if end_date:
                    end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
            else:
                try:
                    days = int(self.filters['days'])
                    end_date = timezone.now().date()
                    start_date = end_date - timedelta(days=days)
                except (ValueError, TypeError):
                    end_date = timezone.now().date()
                    start_date = end_date - timedelta(days=30)
        else:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)

        return start_date, end_date

    def _format_funnel_data(self, breakdown):
        """Format breakdown data for funnel visualization."""
        stages = [
            'registered',
            'verified',
            'rental_requested',
            'rental_completed',
            'license_created',
            'contribution_created',
            'first_broadcast',
            'multiple_broadcasts'
        ]

        funnel_data = []
        for stage in stages:
            if stage in breakdown:
                stage_info = breakdown[stage]
                funnel_data.append({
                    'stage': stage,
                    'name': stage_info['name'],
                    'count': stage_info['count'],
                    'users': stage_info['users']
                })

        return funnel_data

    def _analyze_conversions(self, metrics):
        """Analyze conversion rates between stages."""
        conversion_rates = metrics['conversion_rates']

        analysis = {
            'overall_conversion': {
                'registration_to_verification': conversion_rates['verification_rate'],
                'registration_to_license': conversion_rates['license_creation_rate'],
                'registration_to_broadcast': conversion_rates['first_broadcast_rate'],
                'registration_to_multiple_broadcasts': conversion_rates['multiple_broadcast_rate']
            },
            'rental_conversion': {
                'request_to_completion': conversion_rates['rental_completion_rate'],
                'registration_to_rental_request': conversion_rates['rental_request_rate']
            },
            'content_creation': {
                'license_to_contribution': self._calculate_license_to_contribution_rate(metrics),
                'contribution_to_broadcast': self._calculate_contribution_to_broadcast_rate(metrics)
            }
        }

        return analysis

    def _calculate_license_to_contribution_rate(self, metrics):
        """Calculate rate of licenses that become contributions."""
        licenses_created = metrics['metrics']['licenses_created']
        contributions_created = metrics['metrics']['contributions_created']

        if licenses_created > 0:
            return round((contributions_created / licenses_created) * 100, 2)
        return 0.0

    def _calculate_contribution_to_broadcast_rate(self, metrics):
        """Calculate rate of contributions that get broadcast."""
        contributions_created = metrics['metrics']['contributions_created']
        first_broadcasts = metrics['metrics']['first_broadcasts']

        if contributions_created > 0:
            return round((first_broadcasts / contributions_created) * 100, 2)
        return 0.0

    def _get_trends_data(self, start_date, end_date):
        """Get trends data for the specified period."""
        from ..models import FunnelMetrics

        # Handle 'all' time case
        if not start_date or not end_date:
            # For 'all' time, use a reasonable range (last 2 years)
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=730)  # 2 years

        # Get cached metrics or calculate new ones
        metrics = FunnelMetrics.objects.filter(
            date__range=[start_date, end_date]
        ).order_by('date')

        if not metrics.exists():
            # Cache metrics for the period
            tracker = FunnelTracker()
            current_date = start_date
            while current_date <= end_date:
                tracker.cache_funnel_metrics(current_date)
                current_date += timedelta(days=1)

            metrics = FunnelMetrics.objects.filter(
                date__range=[start_date, end_date]
            ).order_by('date')

        # Format data for charts
        return {
            'dates': [m.date.isoformat() for m in metrics],
            'registrations': [m.total_registrations for m in metrics],
            'verified': [m.verified_users for m in metrics],
            'rental_requests': [m.rental_requests for m in metrics],
            'completed_rentals': [m.completed_rentals for m in metrics],
            'licenses': [m.licenses_created for m in metrics],
            'contributions': [m.contributions_created for m in metrics],
            'first_broadcasts': [m.first_broadcasts for m in metrics],
            'multiple_broadcasts': [m.multiple_broadcasts for m in metrics],
            'conversion_rates': {
                'verification': [m.verification_rate for m in metrics],
                'rental_request': [m.rental_request_rate for m in metrics],
                'rental_completion': [m.rental_completion_rate for m in metrics],
                'license_creation': [m.license_creation_rate for m in metrics],
                'contribution_creation': [m.contribution_creation_rate for m in metrics],
                'first_broadcast': [m.first_broadcast_rate for m in metrics],
                'multiple_broadcast': [m.multiple_broadcast_rate for m in metrics],
            }
        }

    def get_all_data(self):
        """Get all widget data."""
        return {
            'overview': self.get_funnel_overview(),
            'trends': self.get_funnel_trends(),
            'alerts': self.get_alerts_summary()
        }
