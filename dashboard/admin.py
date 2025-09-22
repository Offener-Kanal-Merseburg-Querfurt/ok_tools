from .models import AlertLog
from .models import AlertThreshold
from .models import FunnelMetrics
from .models import UserJourney
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html


# Hide models from admin interface but keep them accessible via API
# @admin.register(UserJourney)
# class UserJourneyAdmin(admin.ModelAdmin):
#     list_display = ['user', 'stage', 'achieved_at', 'rental_request', 'license', 'contribution']
#     list_filter = ['stage', 'achieved_at', 'user__profile__media_authority']
#     search_fields = ['user__email', 'stage']
#     ordering = ['-achieved_at']
#     readonly_fields = ['achieved_at']


# @admin.register(FunnelMetrics)
# class FunnelMetricsAdmin(admin.ModelAdmin):
#     list_display = [
#         'date', 'total_registrations', 'verified_users', 'licenses_created',
#         'first_broadcasts', 'verification_rate', 'license_creation_rate'
#     ]
#     list_filter = ['date', 'created_at']
#     search_fields = ['date']
#     ordering = ['-date']
#     readonly_fields = ['created_at', 'updated_at']


# @admin.register(AlertThreshold)
# class AlertThresholdAdmin(admin.ModelAdmin):
#     list_display = ['name', 'stage', 'metric_type', 'threshold_value', 'comparison_operator', 'is_active']
#     list_filter = ['stage', 'metric_type', 'is_active', 'created_at']
#     search_fields = ['name', 'stage']
#     ordering = ['name']


# @admin.register(AlertLog)
# class AlertLogAdmin(admin.ModelAdmin):
#     list_display = ['threshold', 'triggered_at', 'current_value', 'threshold_value', 'is_resolved']
#     list_filter = ['is_resolved', 'triggered_at', 'threshold__stage', 'threshold__metric_type']
#     search_fields = ['threshold__name', 'message']
#     ordering = ['-triggered_at']
#     readonly_fields = ['triggered_at', 'resolved_at']
