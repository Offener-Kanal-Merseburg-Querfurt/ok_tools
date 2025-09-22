from . import api
from . import views
from django.urls import path


app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_main, name='main'),
    path('users/', views.dashboard_users, name='users'),
    path('licenses/', views.dashboard_licenses, name='licenses'),
    path('contributions/', views.dashboard_contributions, name='contributions'),
    path('projects/', views.dashboard_projects, name='projects'),
    path('inventory/', views.dashboard_inventory, name='inventory'),
    path('notifications/', views.dashboard_notifications, name='notifications'),
    path('funnel/', views.dashboard_funnel, name='funnel'),

    # API endpoints
    path('api/users-statistics/', api.api_users_statistics, name='api_users_statistics'),
    path('api/licenses-statistics/', api.api_licenses_statistics, name='api_licenses_statistics'),
    path('api/contributions-statistics/', api.api_contributions_statistics, name='api_contributions_statistics'),
    path('api/projects-statistics/', api.api_projects_statistics, name='api_projects_statistics'),
    path('api/inventory-statistics/', api.api_inventory_statistics, name='api_inventory_statistics'),
    path('api/notifications-statistics/', api.api_notifications_statistics, name='api_notifications_statistics'),
    path('api/filters-data/', api.api_filters_data, name='api_filters_data'),
    path('api/recent-users/', api.api_recent_users, name='api_recent_users'),
    path('api/recent-licenses/', api.api_recent_licenses, name='api_recent_licenses'),
    path('api/system-status/', api.api_system_status, name='api_system_status'),
    path('api/quick-stats/', api.api_quick_stats, name='api_quick_stats'),

    # Detail view API endpoints
    path('api/users-detail/', api.api_users_detail, name='api_users_detail'),
    path('api/licenses-detail/', api.api_licenses_detail, name='api_licenses_detail'),
    path('api/contributions-detail/', api.api_contributions_detail, name='api_contributions_detail'),
    path('api/projects-detail/', api.api_projects_detail, name='api_projects_detail'),
    path('api/inventory-detail/', api.api_inventory_detail, name='api_inventory_detail'),
    path('api/notifications-detail/', api.api_notifications_detail, name='api_notifications_detail'),

    # Action API endpoints
    path('api/notifications-toggle/<int:notification_id>/', api.api_notifications_toggle, name='api_notifications_toggle'),

    # Funnel and alerts API endpoints
    path('api/funnel-metrics/', api.api_funnel_metrics, name='api_funnel_metrics'),
    path('api/funnel-breakdown/', api.api_funnel_breakdown, name='api_funnel_breakdown'),
    path('api/funnel-trends/', api.api_funnel_trends, name='api_funnel_trends'),
    path('api/funnel-detail/', api.api_funnel_detail, name='api_funnel_detail'),
    path('api/alerts-list/', api.api_alerts_list, name='api_alerts_list'),
    path('api/alerts-resolve/<int:alert_id>/', api.api_alerts_resolve, name='api_alerts_resolve'),
    path('api/thresholds/<int:threshold_id>/', api.api_threshold_update, name='api_threshold_update'),
    path('api/thresholds/<int:threshold_id>/toggle/', api.api_threshold_toggle, name='api_threshold_toggle'),
]
