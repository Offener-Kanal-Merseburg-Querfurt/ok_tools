from datetime import timedelta
from django.db.models import Count
from django.db.models import Q
from django.utils import timezone
from registration.models import Notification
from registration.models import OKUser


class NotificationsWidget:
    """Widget for system notifications management and statistics"""

    def __init__(self, filters=None):
        self.filters = filters or {}
        self._cache = {}

    def get_active_notifications(self):
        """Get currently active notifications"""
        cache_key = f"active_notifications_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        now = timezone.now()

        # Get active notifications within date range
        notifications = Notification.objects.filter(
            is_active=True,
            start_date__lte=now
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gt=now)
        ).order_by('-priority', '-created_at')

        # Apply filters
        if 'notification_type' in self.filters and self.filters['notification_type']:
            notifications = notifications.filter(notification_type=self.filters['notification_type'])

        if 'priority' in self.filters and self.filters['priority']:
            notifications = notifications.filter(priority=self.filters['priority'])

        if 'created_by' in self.filters and self.filters['created_by']:
            notifications = notifications.filter(created_by_id=self.filters['created_by'])

        result = []
        for notification in notifications:
            result.append({
                'id': notification.id,
                'title': notification.title,
                'message': notification.message,
                'notification_type': notification.notification_type,
                'icon': notification.icon,
                'priority': notification.priority,
                'start_date': notification.start_date,
                'end_date': notification.end_date,
                'created_at': notification.created_at,
                'created_by': notification.created_by.email if notification.created_by else None,
                'is_currently_active': notification.is_currently_active()
            })

        self._cache[cache_key] = result
        return result

    def get_notifications_statistics(self):
        """Get statistics about notifications"""
        cache_key = f"notifications_stats_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        now = timezone.now()

        # Date filtering
        date_filter = self._get_date_filter()

        # Base queryset with date filter
        notifications = Notification.objects.filter(**date_filter)

        # Apply additional filters
        if 'notification_type' in self.filters and self.filters['notification_type']:
            notifications = notifications.filter(notification_type=self.filters['notification_type'])

        if 'created_by' in self.filters and self.filters['created_by']:
            notifications = notifications.filter(created_by_id=self.filters['created_by'])

        # Statistics
        total_notifications = notifications.count()
        active_notifications = notifications.filter(is_active=True).count()

        # Currently active (within time range)
        currently_active = notifications.filter(
            is_active=True,
            start_date__lte=now
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gt=now)
        ).count()

        # By type
        by_type = notifications.values('notification_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # By priority
        by_priority = notifications.values('priority').annotate(
            count=Count('id')
        ).order_by('-priority')

        # By creator
        by_creator = notifications.filter(created_by__isnull=False).values(
            'created_by__email'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:5]

        # Recent notifications (last 7 days)
        recent_notifications = notifications.filter(
            created_at__gte=now - timedelta(days=7)
        ).count()

        result = {
            'total_notifications': total_notifications,
            'active_notifications': active_notifications,
            'currently_active': currently_active,
            'recent_notifications': recent_notifications,
            'by_type': list(by_type),
            'by_priority': list(by_priority),
            'by_creator': list(by_creator)
        }

        self._cache[cache_key] = result
        return result

    def get_notification_management_data(self):
        """Get data for notification management interface"""
        cache_key = f"notification_management_{hash(str(self.filters))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Get all notifications for management
        notifications = Notification.objects.all().order_by('-priority', '-created_at')

        # Apply filters
        if 'notification_type' in self.filters and self.filters['notification_type']:
            notifications = notifications.filter(notification_type=self.filters['notification_type'])

        if 'is_active' in self.filters and self.filters['is_active'] != '':
            is_active = self.filters['is_active'].lower() == 'true'
            notifications = notifications.filter(is_active=is_active)

        if 'created_by' in self.filters and self.filters['created_by']:
            notifications = notifications.filter(created_by_id=self.filters['created_by'])

        # Date filtering
        date_filter = self._get_date_filter()
        notifications = notifications.filter(**date_filter)

        result = []
        for notification in notifications:
            result.append({
                'id': notification.id,
                'title': notification.title,
                'message': notification.message,
                'notification_type': notification.notification_type,
                'icon': notification.icon,
                'is_active': notification.is_active,
                'priority': notification.priority,
                'start_date': notification.start_date,
                'end_date': notification.end_date,
                'created_at': notification.created_at,
                'created_by': notification.created_by.email if notification.created_by else None,
                'is_currently_active': notification.is_currently_active(),
                'days_remaining': self._calculate_days_remaining(notification)
            })

        self._cache[cache_key] = result
        return result

    def _get_date_filter(self):
        """Get date filter based on filters"""
        date_filter = {}

        if 'days' in self.filters and self.filters['days']:
            if self.filters['days'] == 'custom':
                if 'start_date' in self.filters and self.filters['start_date']:
                    date_filter['created_at__gte'] = self.filters['start_date']
                if 'end_date' in self.filters and self.filters['end_date']:
                    date_filter['created_at__lte'] = self.filters['end_date']
            else:
                try:
                    days = int(self.filters['days'])
                    date_filter['created_at__gte'] = timezone.now() - timedelta(days=days)
                except (ValueError, TypeError):
                    date_filter['created_at__gte'] = timezone.now() - timedelta(days=30)
        else:
            date_filter['created_at__gte'] = timezone.now() - timedelta(days=30)

        return date_filter

    def _calculate_days_remaining(self, notification):
        """Calculate days remaining for notification"""
        if not notification.end_date:
            return None

        now = timezone.now()
        if notification.end_date <= now:
            return 0

        delta = notification.end_date - now
        return delta.days

    def get_all_data(self):
        """Get all widget data"""
        return {
            'active_notifications': self.get_active_notifications(),
            'statistics': self.get_notifications_statistics(),
            'management_data': self.get_notification_management_data()
        }

    def get_detailed_notifications(self, notification_type=None, page=1, page_size=20):
        """Get detailed list of notifications based on filters with pagination."""

        queryset = Notification.objects.select_related('created_by').all()

        # Apply date filter
        date_filter = self._get_date_filter()
        queryset = queryset.filter(**date_filter)

        # Apply additional filters based on type
        if notification_type == 'active':
            queryset = queryset.filter(is_active=True)
        elif notification_type == 'inactive':
            queryset = queryset.filter(is_active=False)
        elif notification_type == 'high_priority':
            queryset = queryset.filter(priority__gte=8)  # High priority is 8+
        elif notification_type == 'recent':
            from datetime import timedelta
            queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=7))
        elif notification_type == 'currently_active':
            now = timezone.now()
            queryset = queryset.filter(
                is_active=True,
                start_date__lte=now
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gt=now)
            )
        elif notification_type == 'total':
            # No additional filtering for total
            pass

        # Apply existing filters
        if 'notification_type' in self.filters and self.filters['notification_type']:
            queryset = queryset.filter(notification_type=self.filters['notification_type'])

        if 'created_by' in self.filters and self.filters['created_by']:
            queryset = queryset.filter(created_by_id=self.filters['created_by'])

        # Order by priority and creation date
        queryset = queryset.order_by('-priority', '-created_at')

        # Calculate pagination
        total_count = queryset.count()
        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        # Get paginated data
        paginated_queryset = queryset[start_index:end_index]

        # Get detailed notification data
        notifications_data = []
        for notification in paginated_queryset:
            notification_data = {
                'id': notification.id,
                'title': notification.title or "",
                'message': notification.message or "",
                'notification_type': notification.notification_type or "",
                'icon': notification.icon or "",
                'is_active': notification.is_active,
                'priority': notification.priority or "",
                'start_date': notification.start_date.strftime('%Y-%m-%d %H:%M') if notification.start_date else "",
                'end_date': notification.end_date.strftime('%Y-%m-%d %H:%M') if notification.end_date else "",
                'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M') if notification.created_at else "",
                'created_by': notification.created_by.email if notification.created_by else "",
                'is_currently_active': notification.is_currently_active(),
                'days_remaining': self._calculate_days_remaining(notification)
            }
            notifications_data.append(notification_data)

        # Calculate pagination info
        total_pages = (total_count + page_size - 1) // page_size
        has_next = page < total_pages
        has_previous = page > 1

        return {
            'notifications': notifications_data,
            'total_count': total_count,
            'displayed_count': len(notifications_data),
            'pagination': {
                'current_page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_previous': has_previous,
                'start_index': start_index + 1 if total_count > 0 else 0,
                'end_index': min(start_index + page_size, total_count)
            }
        }
