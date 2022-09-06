from .models import Contribution
from django.contrib import admin
from django.contrib.admin.decorators import display
from django.utils.translation import gettext_lazy as _


class ContributionAdmin(admin.ModelAdmin):
    """How should the Contribution be shown on the admin site."""

    list_display = (
        '__str__',
        'get_user',
        'broadcast_date',
    )

    ordering = ['-broadcast_date']

    @display(description=_('User'))
    def get_user(self, obj):
        """Return the first an last name of the contributions user."""
        return (f'{obj.license.profile.first_name}'
                f' {obj.license.profile.last_name}')


admin.site.register(Contribution, ContributionAdmin)
