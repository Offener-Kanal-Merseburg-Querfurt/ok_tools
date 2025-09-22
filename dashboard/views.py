from .widgets.users import UsersWidget
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _


def is_admin(user):
    """Check if user is admin."""
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(is_admin)
def dashboard_main(request):
    """Main dashboard view."""
    context = {
        'page_title': _('Main Dashboard'),
        'active_tab': 'dashboard',
        'is_main_dashboard': True,
    }
    return render(request, 'dashboard/main.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_users(request):
    """Users widget view."""
    # Initialize users widget
    users_widget = UsersWidget(request)

    context = {
        'page_title': _('Users Statistics'),
        'active_tab': 'users',
        'widget_data': users_widget.get_all_data(),
    }
    return render(request, 'dashboard/widgets/users.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_licenses(request):
    """Licenses widget view."""
    context = {
        'page_title': _('Licenses Statistics'),
        'active_tab': 'licenses',
    }
    return render(request, 'dashboard/widgets/licenses.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_contributions(request):
    """Contributions widget view."""
    context = {
        'page_title': _('Contributions Statistics'),
        'active_tab': 'contributions',
    }
    return render(request, 'dashboard/widgets/contributions.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_projects(request):
    """Projects widget view."""
    context = {
        'page_title': _('Projects Statistics'),
        'active_tab': 'projects',
    }
    return render(request, 'dashboard/widgets/projects.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_inventory(request):
    """Inventory widget view."""
    context = {
        'page_title': _('Rental Statistics'),
        'active_tab': 'inventory',
    }
    return render(request, 'dashboard/widgets/inventory.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_notifications(request):
    """Notifications widget view."""
    context = {
        'page_title': _('System Notifications'),
        'active_tab': 'notifications',
    }
    return render(request, 'dashboard/widgets/notifications.html', context)


@login_required
@user_passes_test(is_admin)
def dashboard_funnel(request):
    """User participation funnel widget view."""
    context = {
        'page_title': _('User Participation Funnel'),
        'active_tab': 'funnel',
    }
    return render(request, 'dashboard/widgets/funnel.html', context)
