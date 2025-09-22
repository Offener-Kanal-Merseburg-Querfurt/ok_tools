from contributions.models import Contribution
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from licenses.models import License
from registration.models import OKUser
from registration.models import Profile
from rental.models import RentalRequest


class UserJourneyStage(models.TextChoices):
    """Stages in the user participation funnel."""

    REGISTERED = 'registered', _('Registered')
    VERIFIED = 'verified', _('Verified')
    RENTAL_REQUESTED = 'rental_requested', _('Rental Requested')
    RENTAL_COMPLETED = 'rental_completed', _('Rental Completed')
    LICENSE_CREATED = 'license_created', _('License Created')
    CONTRIBUTION_CREATED = 'contribution_created', _('Contribution Created')
    FIRST_BROADCAST = 'first_broadcast', _('First Broadcast')
    MULTIPLE_BROADCASTS = 'multiple_broadcasts', _('Multiple Broadcasts')


class UserJourney(models.Model):
    """Track user's journey through the participation funnel."""

    user = models.ForeignKey(
        OKUser,
        on_delete=models.CASCADE,
        verbose_name=_('User'),
        related_name='journey_stages'
    )

    stage = models.CharField(
        max_length=30,
        choices=UserJourneyStage.choices,
        verbose_name=_('Stage')
    )

    achieved_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_('Achieved At')
    )

    # Optional references to related objects
    rental_request = models.ForeignKey(
        RentalRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Rental Request')
    )

    license = models.ForeignKey(
        License,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('License')
    )

    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Contribution')
    )

    # Additional metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('Metadata')
    )

    class Meta:
        verbose_name = _('User Journey Stage')
        verbose_name_plural = _('User Journey Stages')
        ordering = ['user', 'achieved_at']
        unique_together = ['user', 'stage']

    def __str__(self):
        return f"{self.user.email} - {self.get_stage_display()}"


class FunnelMetrics(models.Model):
    """Cached funnel metrics for performance."""

    date = models.DateField(
        verbose_name=_('Date'),
        unique=True
    )

    # Registration metrics
    total_registrations = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Total Registrations')
    )

    verified_users = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Verified Users')
    )

    # Rental metrics
    rental_requests = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Rental Requests')
    )

    completed_rentals = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Completed Rentals')
    )

    # License metrics
    licenses_created = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Licenses Created')
    )

    # Contribution metrics
    contributions_created = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Contributions Created')
    )

    first_broadcasts = models.PositiveIntegerField(
        default=0,
        verbose_name=_('First Broadcasts')
    )

    multiple_broadcasts = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Multiple Broadcasts')
    )

    # Conversion rates (stored as percentages)
    verification_rate = models.FloatField(
        default=0.0,
        verbose_name=_('Verification Rate (%)')
    )

    rental_request_rate = models.FloatField(
        default=0.0,
        verbose_name=_('Rental Request Rate (%)')
    )

    rental_completion_rate = models.FloatField(
        default=0.0,
        verbose_name=_('Rental Completion Rate (%)')
    )

    license_creation_rate = models.FloatField(
        default=0.0,
        verbose_name=_('License Creation Rate (%)')
    )

    contribution_creation_rate = models.FloatField(
        default=0.0,
        verbose_name=_('Contribution Creation Rate (%)')
    )

    first_broadcast_rate = models.FloatField(
        default=0.0,
        verbose_name=_('First Broadcast Rate (%)')
    )

    multiple_broadcast_rate = models.FloatField(
        default=0.0,
        verbose_name=_('Multiple Broadcast Rate (%)')
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created At')
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Updated At')
    )

    class Meta:
        verbose_name = _('Funnel Metrics')
        verbose_name_plural = _('Funnel Metrics')
        ordering = ['-date']

    def __str__(self):
        return f"Funnel Metrics - {self.date}"


class AlertThreshold(models.Model):
    """Configuration for alert thresholds."""

    name = models.CharField(
        max_length=100,
        verbose_name=_('Alert Name')
    )

    metric_type = models.CharField(
        max_length=50,
        choices=[
            ('conversion_rate', _('Conversion Rate')),
            ('absolute_count', _('Absolute Count')),
            ('trend_change', _('Trend Change')),
        ],
        verbose_name=_('Metric Type')
    )

    stage = models.CharField(
        max_length=30,
        choices=UserJourneyStage.choices,
        verbose_name=_('Stage')
    )

    threshold_value = models.FloatField(
        verbose_name=_('Threshold Value')
    )

    comparison_operator = models.CharField(
        max_length=10,
        choices=[
            ('lt', _('Less Than')),
            ('lte', _('Less Than or Equal')),
            ('gt', _('Greater Than')),
            ('gte', _('Greater Than or Equal')),
            ('eq', _('Equal')),
        ],
        verbose_name=_('Comparison Operator')
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is Active')
    )

    notification_recipients = models.JSONField(
        default=list,
        verbose_name=_('Notification Recipients')
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created At')
    )

    class Meta:
        verbose_name = _('Alert Threshold')
        verbose_name_plural = _('Alert Thresholds')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.get_stage_display()}"


class AlertLog(models.Model):
    """Log of triggered alerts."""

    threshold = models.ForeignKey(
        AlertThreshold,
        on_delete=models.CASCADE,
        verbose_name=_('Threshold')
    )

    triggered_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Triggered At')
    )

    current_value = models.FloatField(
        verbose_name=_('Current Value')
    )

    threshold_value = models.FloatField(
        verbose_name=_('Threshold Value')
    )

    message = models.TextField(
        verbose_name=_('Message')
    )

    is_resolved = models.BooleanField(
        default=False,
        verbose_name=_('Is Resolved')
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Resolved At')
    )

    class Meta:
        verbose_name = _('Alert Log')
        verbose_name_plural = _('Alert Logs')
        ordering = ['-triggered_at']

    def __str__(self):
        return f"Alert: {self.threshold.name} - {self.triggered_at}"
