from .forms import RentalIssueForm
from .forms import RentalRequestAdminForm
from .forms import RentalTransactionForm
from .models import EquipmentSet
from .models import EquipmentSetItem
from .models import RentalIssue
from .models import RentalItem
from .models import RentalProcessProxy
from .models import RentalRequest
from .models import RentalTransaction
from .models import Room
from .models import RoomRental
from django import forms
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import path
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_admin_listfilter_dropdown.filters import DropdownFilter
from django_admin_listfilter_dropdown.filters import RelatedDropdownFilter


class RentalItemInline(admin.TabularInline):
    """Inline editor for rental items within a rental request."""

    model = RentalItem
    extra = 0
    fields = (
        "inventory_item",
        "quantity_requested",
        "quantity_issued",
        "quantity_returned",
        "actual_return_date",
        "notes",
    )
    readonly_fields = ("actual_return_date",)
    autocomplete_fields = ("inventory_item",)


class RentalTransactionInline(admin.TabularInline):
    """Inline editor for rental transactions related to a rental item."""

    model = RentalTransaction
    extra = 0
    fields = ("transaction_type", "quantity", "performed_by", "performed_at", "condition", "notes")
    readonly_fields = ("performed_at",)


class RentalIssueInline(admin.TabularInline):
    """Inline editor for issues discovered during return of a rental item."""

    model = RentalIssue
    extra = 0
    fields = ("issue_type", "severity", "reported_by", "reported_at", "resolved", "resolution_notes", "description")
    readonly_fields = ("reported_at",)


class RoomRentalInline(admin.TabularInline):
    """Inline editor to attach rooms to a rental request."""

    model = RoomRental
    extra = 0
    fields = ("room", "people_count", "notes")
    autocomplete_fields = ("room",)


@admin.register(RentalRequest)
class RentalRequestAdmin(admin.ModelAdmin):
    """Admin configuration for ``RentalRequest`` objects."""

    form = RentalRequestAdminForm
    list_display = (
        "project_name",
        "user",
        "rental_type",
        "requested_start_date",
        "requested_end_date",
        "status",
        "created_at",
        "total_items_count",
        "total_rooms_count",
    )
    list_filter = (
        "status",
        "rental_type",
        ("created_at", admin.DateFieldListFilter),
        ("requested_start_date", admin.DateFieldListFilter),
        ("requested_end_date", admin.DateFieldListFilter),
    )
    search_fields = ("project_name", "purpose", "user__email", "created_by__email")
    inlines = [RentalItemInline, RoomRentalInline]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_('Meta'), {
            'fields': ("status", "created_at", "updated_at"),
        }),
        (_('Actors'), {
            'fields': ("user", "created_by"),
        }),
        (_('Project'), {
            'fields': ("project_name", "purpose", "rental_type"),
        }),
        (_('Dates'), {
            'fields': ("requested_start_date", "requested_end_date", "actual_start_date", "actual_end_date"),
        }),
        (_('Notes'), {
            'fields': ("notes",),
        }),
    )

    def changelist_view(self, request, extra_context=None):
        """Inject link to the rental process page into changelist context."""
        extra_context = extra_context or {}
        extra_context['rental_process_url'] = '/rental/admin/rental-process/'
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(RentalItem)
class RentalItemAdmin(admin.ModelAdmin):
    """Admin configuration for ``RentalItem`` records."""

    list_display = (
        "rental_request",
        "inventory_item",
        "quantity_requested",
        "quantity_issued",
        "quantity_returned",
        "actual_return_date",
        "is_overdue_display",
    )
    search_fields = (
        "rental_request__project_name",
        "inventory_item__inventory_number",
        "inventory_item__description",
        "inventory_item__manufacturer__name",
    )
    autocomplete_fields = ("inventory_item", "rental_request")
    inlines = [RentalTransactionInline, RentalIssueInline]
    list_filter = (
        ("rental_request__requested_start_date", admin.DateFieldListFilter),
        ("rental_request__requested_end_date", admin.DateFieldListFilter),
    )
    fieldsets = (
        (None, {
            'fields': ("rental_request", "inventory_item"),
        }),
        (_('Quantities'), {
            'fields': ("quantity_requested", "quantity_issued", "quantity_returned"),
        }),
        (_('Return Information'), {
            'fields': ("actual_return_date",),
        }),
        (_('Notes'), {
            'fields': ("notes",),
        }),
    )
    readonly_fields = ("actual_return_date",)

    def is_overdue_display(self, obj):
        """Display overdue status with a colored indicator."""
        if obj.is_overdue:
            days = obj.days_overdue
            if days > 0:
                return f"🔴 {days} days overdue"
            else:
                return "🔴 Overdue"
        return "🟢 On time"
    is_overdue_display.short_description = _('Overdue Status')


class EquipmentSetItemInline(admin.TabularInline):
    """Inline editor for items inside an equipment set."""

    model = EquipmentSetItem
    extra = 0
    fields = ("inventory_item", "quantity", "is_required", "notes")


@admin.register(EquipmentSet)
class EquipmentSetAdmin(admin.ModelAdmin):
    """Admin configuration for equipment sets management."""

    list_display = ("name", "is_template", "is_active", "created_by", "created_at")
    list_filter = ("is_template", "is_active")
    search_fields = ("name", "description")
    inlines = [EquipmentSetItemInline]
    change_list_template = 'admin/rental/equipment_set_change_list.html'

    def get_urls(self):
        """Register custom URLs for creating rentals from sets."""
        urls = super().get_urls()
        custom_urls = [
            path('rent/', self.admin_site.admin_view(self.rent_sets_view), name='rental_equipmentset_rent'),
        ]
        return custom_urls + urls

    class RentSetsForm(forms.Form):
        """Form to create a rental request from selected equipment sets."""

        equipment_sets = forms.ModelMultipleChoiceField(
            queryset=EquipmentSet.objects.filter(is_active=True),
            widget=admin.widgets.FilteredSelectMultiple(_('Equipment sets'), is_stacked=False),
            required=True,
            label=_('Equipment sets')
        )
        user = forms.ModelChoiceField(
            queryset=RentalRequest._meta.get_field('user').remote_field.model.objects.all(),
            required=True,
            label=_('User')
        )
        created_by = forms.ModelChoiceField(
            queryset=RentalRequest._meta.get_field('created_by').remote_field.model.objects.all(),
            required=True,
            label=_('Created by')
        )
        project_name = forms.CharField(max_length=255, required=True, label=_('Project name'))
        purpose = forms.CharField(widget=forms.Textarea, required=True, label=_('Purpose'))
        requested_start_date = forms.DateTimeField(initial=timezone.now, label=_('Requested start date'))
        requested_end_date = forms.DateTimeField(label=_('Requested end date'))

    def rent_sets_view(self, request):
        """Handle form for creating rental request from equipment sets."""
        if request.method == 'POST':
            form = self.RentSetsForm(request.POST)
            if form.is_valid():
                rental_request = RentalRequest.objects.create(
                    user=form.cleaned_data['user'],
                    created_by=form.cleaned_data['created_by'],
                    project_name=form.cleaned_data['project_name'],
                    purpose=form.cleaned_data['purpose'],
                    requested_start_date=form.cleaned_data['requested_start_date'],
                    requested_end_date=form.cleaned_data['requested_end_date'],
                    status='reserved',
                )
                for equipment_set in form.cleaned_data['equipment_sets']:
                    equipment_set.apply_to_rental_request(rental_request)
                self.message_user(request, _('Rental request created: %s') % rental_request)
                return redirect('admin:rental_rentalrequest_change', rental_request.pk)
        else:
            initial_created_by = getattr(request, 'user', None)
            form = self.RentSetsForm(initial={'created_by': initial_created_by})
        context = {
            **self.admin_site.each_context(request),
            'title': _('Create rental from equipment sets'),
            'form': form,
            'opts': self.model._meta,
        }
        return render(request, 'admin/rental/rent_sets_form.html', context)

    def each_context(self, request):
        """Augment default admin context with rental process link."""
        ctx = super().each_context(request)
        ctx['rental_process_url'] = '/rental/admin/rental-process/'
        return ctx


@admin.register(RentalTransaction)
class RentalTransactionAdmin(admin.ModelAdmin):
    """Admin configuration for rental transactions."""

    form = RentalTransactionForm
    list_display = ("rental_item", "transaction_type", "quantity", "performed_by", "performed_at", "condition")
    list_filter = ("transaction_type", "condition", "performed_at")
    search_fields = ("rental_item__rental_request__project_name", "rental_item__inventory_item__inventory_number")
    autocomplete_fields = ("rental_item", "performed_by")
    readonly_fields = ("performed_at",)


@admin.register(RentalIssue)
class RentalIssueAdmin(admin.ModelAdmin):
    """Admin configuration for rental issues management."""

    form = RentalIssueForm
    list_display = ("rental_item", "issue_type", "severity", "reported_by", "reported_at", "resolved")
    list_filter = ("issue_type", "severity", "resolved")
    search_fields = ("rental_item__rental_request__project_name", "rental_item__inventory_item__inventory_number")
    autocomplete_fields = ("rental_item", "reported_by")
    readonly_fields = ("reported_at",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Admin interface for room management."""

    list_display = ['name', 'capacity', 'location', 'is_active', 'description_short']
    list_filter = ['is_active', 'location']
    search_fields = ['name', 'description', 'location']
    ordering = ['name']

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_active'),
        }),
        (_('Capacity & Location'), {
            'fields': ('capacity', 'location'),
        }),
    )

    def description_short(self, obj):
        """Return truncated description for list view."""
        return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
    description_short.short_description = _('Description')


@admin.register(RoomRental)
class RoomRentalAdmin(admin.ModelAdmin):
    """Admin interface for room rental management."""

    list_display = ['room', 'rental_request', 'people_count', 'rental_status', 'rental_dates']
    list_filter = [
        ('room', admin.RelatedFieldListFilter),
        ('rental_request__status', admin.ChoicesFieldListFilter),
    ]
    search_fields = ['room__name', 'rental_request__project_name', 'rental_request__user__email']
    autocomplete_fields = ['room', 'rental_request']

    fieldsets = (
        (None, {
            'fields': ('rental_request', 'room'),
        }),
        (_('Details'), {
            'fields': ('people_count', 'notes'),
        }),
    )

    def rental_status(self, obj):
        """Return rental status with a color indicator."""
        status = obj.rental_request.status
        colors = {
            'draft': 'gray',
            'reserved': 'orange',
            'issued': 'blue',
            'returned': 'green',
            'cancelled': 'red',
        }
        color = colors.get(status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.rental_request.get_status_display()
        )
    rental_status.short_description = _('Status')

    def rental_dates(self, obj):
        """Return rental dates range string."""
        start = obj.rental_request.requested_start_date.strftime('%d.%m.%Y %H:%M')
        end = obj.rental_request.requested_end_date.strftime('%d.%m.%Y %H:%M')
        return f"{start} - {end}"
    rental_dates.short_description = _('Rental dates')


@admin.register(RentalProcessProxy)
class RentalProcessProxyAdmin(admin.ModelAdmin):
    """Custom admin for rental process link; redirects to rental process page."""

    def changelist_view(self, request, extra_context=None):
        """Redirect to rental process page instead of showing changelist."""
        return HttpResponseRedirect(reverse('rental:admin_rental_process'))

    def add_view(self, request, form_url='', extra_context=None):
        """Redirect to rental process page instead of showing add form."""
        return HttpResponseRedirect(reverse('rental:rental:admin_rental_process'))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Redirect to rental process page instead of showing change form."""
        return HttpResponseRedirect(reverse('rental:admin_rental_process'))

    def has_add_permission(self, request):
        """Allow 'add' permission to show the link."""
        return request.user.is_staff

    def has_change_permission(self, request, obj=None):
        """Allow 'change' permission to show the link."""
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        """Disable delete permission."""
        return False
