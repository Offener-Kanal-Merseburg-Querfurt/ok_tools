from dashboard.models import AlertThreshold
from dashboard.models import UserJourneyStage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Setup default alert thresholds for the funnel'

    def handle(self, *args, **options):
        self.stdout.write("Setting up default alert thresholds...")

        # Default thresholds
        thresholds = [
            {
                'name': 'Low Verification Rate',
                'metric_type': 'conversion_rate',
                'stage': UserJourneyStage.VERIFIED,
                'threshold_value': 50.0,
                'comparison_operator': 'lt',
                'notification_recipients': ['admin@ok-tools.de']
            },
            {
                'name': 'Low License Creation Rate',
                'metric_type': 'conversion_rate',
                'stage': UserJourneyStage.LICENSE_CREATED,
                'threshold_value': 10.0,
                'comparison_operator': 'lt',
                'notification_recipients': ['admin@ok-tools.de']
            },
            {
                'name': 'Low Broadcast Rate',
                'metric_type': 'conversion_rate',
                'stage': UserJourneyStage.FIRST_BROADCAST,
                'threshold_value': 5.0,
                'comparison_operator': 'lt',
                'notification_recipients': ['admin@ok-tools.de']
            },
            {
                'name': 'High Registration Count',
                'metric_type': 'absolute_count',
                'stage': UserJourneyStage.REGISTERED,
                'threshold_value': 100.0,
                'comparison_operator': 'gt',
                'notification_recipients': ['admin@ok-tools.de']
            },
            {
                'name': 'Low Rental Completion Rate',
                'metric_type': 'conversion_rate',
                'stage': UserJourneyStage.RENTAL_COMPLETED,
                'threshold_value': 80.0,
                'comparison_operator': 'lt',
                'notification_recipients': ['admin@ok-tools.de']
            }
        ]

        created_count = 0
        updated_count = 0

        for threshold_data in thresholds:
            threshold, created = AlertThreshold.objects.get_or_create(
                name=threshold_data['name'],
                defaults=threshold_data
            )

            if created:
                created_count += 1
                self.stdout.write(f"Created threshold: {threshold.name}")
            else:
                # Update existing threshold
                for key, value in threshold_data.items():
                    setattr(threshold, key, value)
                threshold.save()
                updated_count += 1
                self.stdout.write(f"Updated threshold: {threshold.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Setup completed: {created_count} created, {updated_count} updated"
            )
        )
