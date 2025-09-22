from dashboard.models import AlertThreshold
from dashboard.utils import AlertManager
from dashboard.utils import FunnelTracker
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
import logging


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check alert thresholds and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to check metrics for'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually sending notifications'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']

        self.stdout.write(f"Checking alerts for the last {days} days...")

        try:
            # Get funnel metrics for the period
            tracker = FunnelTracker()
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days)

            metrics = tracker.get_funnel_metrics(start_date, end_date)

            # Check thresholds
            alert_manager = AlertManager()
            triggered_alerts = alert_manager.check_thresholds(metrics)

            if triggered_alerts:
                self.stdout.write(
                    self.style.WARNING(f"Triggered {len(triggered_alerts)} alerts:")
                )
                for alert in triggered_alerts:
                    self.stdout.write(f"  - {alert.message}")
            else:
                self.stdout.write(
                    self.style.SUCCESS("No alerts triggered")
                )

            # Cache metrics for performance
            tracker.cache_funnel_metrics(end_date)

            self.stdout.write(
                self.style.SUCCESS("Alert check completed successfully")
            )

        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
            self.stdout.write(
                self.style.ERROR(f"Error checking alerts: {e}")
            )
            raise
