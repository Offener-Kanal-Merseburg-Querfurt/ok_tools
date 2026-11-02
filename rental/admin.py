from .forms import RentalIssueForm
from .forms import RentalRequestAdminForm
from .forms import RentalTransactionForm
from .models import EquipmentSet
from .models import EquipmentSetItem
from .models import LabelFormat
from .models import LabelLine
from .models import RentalConfig
from .models import RentalConsumable
from .models import RentalIssue
from .models import RentalItem
from .models import RentalProcessProxy
from .models import RentalRequest
from .models import RentalTransaction
from .models import Room
from .models import RoomImage
from .models import RoomRental
from .working_hours import validate_working_hours_period
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


class RentalConsumableInline(admin.TabularInline):
    """Inline editor for consumables handed out with a rental."""

    model = RentalConsumable
    extra = 0
    fields = ("name", "quantity", "quantity_returned", "status", "notes", "reminder_count", "last_reminder_sent_at")
    readonly_fields = ("reminder_count", "last_reminder_sent_at")


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
    change_form_template = 'admin/rental/rentalrequest/change_form.html'
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
        "has_signature",
    )
    list_filter = (
        "status",
        "rental_type",
        ("created_at", admin.DateFieldListFilter),
        ("requested_start_date", admin.DateFieldListFilter),
        ("requested_end_date", admin.DateFieldListFilter),
    )
    search_fields = ("project_name", "purpose", "user__email", "created_by__email")
    inlines = [RentalItemInline, RoomRentalInline, RentalConsumableInline]
    readonly_fields = (
        "created_at",
        "updated_at",
        "has_signature_display",
        "auto_return_reminder_sent_at",
    )
    fieldsets = (
        (_('Meta'), {
            'fields': (
                "status",
                "created_at",
                "updated_at",
                "has_signature_display",
                "auto_return_reminder_sent_at",
            ),
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

    def has_signature(self, obj):
        """Display signature status in list view."""
        if not obj.pk:
            return '-'
        if obj.has_any_signature():
            return format_html(
                '<span style="color: #28a745;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {}</span>',
                _('Yes')
            )
        else:
            return format_html(
                '<span style="color: #999;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> {}</span>',
                _('No')
            )

    has_signature.short_description = _('Signature')
    has_signature.admin_order_field = 'signature'

    def has_signature_display(self, obj):
        """Display signature status in change form."""
        if not obj.pk:
            return '-'
        if obj.has_any_signature():
            return format_html(
                '<span style="color: #28a745; font-weight: bold;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {}</span>',
                _('Digital signature is present')
            )
        else:
            return format_html(
                '<span style="color: #999;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> {}</span>',
                _('No digital signature')
            )

    has_signature_display.short_description = _('Digital Signature')

    # PERFORMANCE OPTIMIZATION: Reduce N+1 queries in list view
    def get_queryset(self, request):
        """Optimize queryset with select_related and prefetch_related."""
        return super().get_queryset(request).select_related(
            'user',
            'created_by',
            'user__profile'
        ).prefetch_related(
            'items__inventory_item',
            'room_rentals__room'
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

    # PERFORMANCE OPTIMIZATION: Reduce N+1 queries in list view
    def get_queryset(self, request):
        """Optimize queryset with select_related for foreign keys."""
        return super().get_queryset(request).select_related(
            'rental_request',
            'rental_request__user',
            'inventory_item',
            'inventory_item__manufacturer',
            'inventory_item__category',
            'inventory_item__location'
        )

    def is_overdue_display(self, obj):
        """Display overdue status with a colored indicator."""
        if obj.is_overdue:
            days = obj.days_overdue
            if days > 0:
                return format_html(
                    '<span style="color: #dc3545;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> {} {}</span>',
                    days,
                    _('days overdue')
                )
            else:
                return format_html(
                    '<span style="color: #dc3545;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> {}</span>',
                    _('Overdue')
                )
        return format_html(
            '<span style="color: #28a745;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {}</span>',
            _('On time')
        )
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
                requested_start_date = form.cleaned_data['requested_start_date']
                requested_end_date = form.cleaned_data['requested_end_date']
                is_valid_period, error_message = validate_working_hours_period(
                    requested_start_date,
                    requested_end_date,
                    request.user,
                )
                if not is_valid_period:
                    form.add_error(None, error_message)
                else:
                    rental_request = RentalRequest.objects.create(
                        user=form.cleaned_data['user'],
                        created_by=form.cleaned_data['created_by'],
                        project_name=form.cleaned_data['project_name'],
                        purpose=form.cleaned_data['purpose'],
                        requested_start_date=requested_start_date,
                        requested_end_date=requested_end_date,
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


class RoomImageClearableFileInput(forms.ClearableFileInput):
    """File widget whose "Currently" link points at the ``room_image`` view.

    Django's default links the current file to ``value.url`` (``/media/...``),
    which 404s on the separate nginx VM. Routing it through the view keeps the
    link working, consistent with the preview thumbnail.
    """

    template_name = 'rental/widgets/room_image_clearable.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        instance = getattr(value, 'instance', None)
        pk = getattr(instance, 'pk', None)
        if context['widget'].get('is_initial') and pk:
            context['widget']['value_url'] = reverse(
                'rental:room_image', args=[pk])
        return context


class RoomImageInline(admin.TabularInline):
    """Inline admin for room photos with a small preview."""

    model = RoomImage
    extra = 1
    fields = ('image', 'preview', 'caption', 'sort_order')
    readonly_fields = ('preview',)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Serve the image field's "Currently" link through the view."""
        if db_field.name == 'image':
            kwargs['widget'] = RoomImageClearableFileInput
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description=_('Preview'))
    def preview(self, obj):
        """Return a small thumbnail that opens the room's photo carousel.

        Served through the ``room_image`` view rather than ``obj.image.url``:
        in the split deployment nginx cannot reach the app's media folder, so
        the static ``/media/`` URL 404s (see ``rental.views.serve_room_image``).
        Photos of the same room share a lightbox group, so a click pages
        through them all.
        """
        if obj and obj.pk and obj.image:
            full = reverse('rental:room_image', args=[obj.pk])
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" '
                'data-lightbox="{}" data-lightbox-caption="{}" '
                'data-lightbox-group="room-{}" title="{}">'
                '<img src="{}?size=thumb" style="height:80px;width:80px;'
                'object-fit:cover;border-radius:6px;border:1px solid #ccc;'
                'cursor:zoom-in;"></a>',
                full,
                full,
                obj.caption or obj.image.name.rsplit('/', 1)[-1],
                obj.room_id,
                _('Click to enlarge'),
                full,
            )
        return '—'


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Admin interface for room management."""

    class Media:
        """Room photos open in the shared carousel lightbox."""

        js = ('rental/js/lightbox.js',)

    list_display = ['name', 'capacity', 'location', 'is_active', 'photo_count', 'description_short']
    list_filter = ['is_active', 'location']
    search_fields = ['name', 'description', 'location']
    ordering = ['name']
    inlines = [RoomImageInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_active'),
        }),
        (_('Capacity & Location'), {
            'fields': ('capacity', 'location'),
        }),
    )

    def get_queryset(self, request):
        """Prefetch images to avoid N+1 in the list view."""
        return super().get_queryset(request).prefetch_related('images')

    @admin.display(description=_('Photos'))
    def photo_count(self, obj):
        """Return the number of photos attached to the room."""
        return obj.images.count()


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
        return HttpResponseRedirect(reverse('rental:admin_rental_process'))

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


class LabelLineInline(admin.TabularInline):
    """The lines a label format prints, in order."""

    model = LabelLine
    extra = 0
    verbose_name_plural = _('Label lines — what this label prints')
    classes = ('label-lines',)
    fields = ('position', 'content', 'size', 'align', 'shorten_words',
              'highlight_codes', 'drop_leading_segments')
    ordering = ('position', 'pk')


@admin.register(LabelFormat)
class LabelFormatAdmin(admin.ModelAdmin):
    """Admin interface for the label sizes the print dialog offers."""

    list_display = ('name', 'size_label', 'slug', 'gap_mm', 'is_active',
                    'sort_order')
    list_editable = ('is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [LabelLineInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', ('width_mm', 'height_mm'), 'gap_mm'),
            'description': _('The barcode geometry and the type sizes are '
                             'derived from these millimetres, so a new roll '
                             'needs nothing else.'),
        }),
        (_('Availability'), {
            'fields': ('is_active', 'sort_order'),
            'description': _('A format without lines prints the default '
                             'layout: inventory number and owner, the '
                             'barcode, the description, then the location '
                             'with its codes enlarged.'),
        }),
    )

    @admin.display(description=_('Size'))
    def size_label(self, obj):
        """Return the label size for the changelist."""
        return obj.size_label


@admin.register(RentalConsumable)
class RentalConsumableAdmin(admin.ModelAdmin):
    """Admin list of consumables handed out with rentals."""

    list_display = ("name", "quantity", "quantity_returned", "status", "rental_request",
                    "returned_at", "reminder_count", "last_reminder_sent_at")
    list_filter = ("status",)
    search_fields = ("name", "rental_request__project_name", "rental_request__user__email",
                     "rental_request__user__profile__first_name", "rental_request__user__profile__last_name")
    raw_id_fields = ("rental_request", "created_by", "resolved_by")


@admin.register(RentalConfig)
class RentalConfigAdmin(admin.ModelAdmin):
    """Admin interface for RentalConfig model."""

    filter_horizontal = ['user_organizations', 'member_organizations',
                         'employee_organizations', 'rental_only_organizations']

    fieldsets = (
        (_('Approval workflow'), {
            'fields': (
                'user_request_requires_approval',
                'site_base_url',
                'request_url_template',
                'approval_recipient_emails',
                'approval_token_max_age_seconds',
            ),
        }),
        (_('Automatic Reminders'), {
            'fields': (
                'auto_reminder_enabled',
                'auto_reminder_hours_before',
                'missing_consumable_reminder_days',
            ),
            'description': _('Send automatic return reminder emails before the return deadline.'),
        }),
        (_('Photos'), {
            'fields': (
                'show_item_photos',
                'show_room_photos',
            ),
            'description': _('Show item and room photos on the rental frontend pages.'),
        }),
        (_('Barcode scanning'), {
            'fields': (
                'scan_sound_enabled',
            ),
            'description': _('Audible feedback while scanning on the issue and '
                             'return screens.'),
        }),
        (_('Label printer'), {
            'fields': (
                'label_printer_host',
                ('label_printer_port', 'label_printer_dpi'),
                ('label_gap_mm', 'label_printer_density', 'label_printer_speed'),
                ('label_offset_x_mm', 'label_offset_y_mm'),
            ),
            'description': _('A network label printer speaking TSPL (e.g. TSC '
                             'TE210). With a host set, roll labels can be sent '
                             'to it directly, which needs no media size, margin '
                             'or orientation set up on the workstation. Leave '
                             'the host empty to print through the browser only.'),
        }),
        (_('Working hours'), {
            'fields': (
                ('monday_start_time', 'monday_end_time'),
                ('tuesday_start_time', 'tuesday_end_time'),
                ('wednesday_start_time', 'wednesday_end_time'),
                ('thursday_start_time', 'thursday_end_time'),
                ('friday_start_time', 'friday_end_time'),
                ('saturday_start_time', 'saturday_end_time'),
                ('sunday_start_time', 'sunday_end_time'),
            ),
            'description': _('Leave both fields empty to mark a day as closed.'),
        }),
        (_('Organization Access'), {
            'fields': ('user_organizations', 'member_organizations',
                       'employee_organizations', 'rental_only_organizations'),
            'description': _('Leave a list empty to fall back to the default '
                             'organizations for that user type.'),
        }),
    )

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        formfield = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name in ('user_organizations', 'member_organizations',
                             'employee_organizations',
                             'rental_only_organizations'):
            formfield.widget.can_add_related = False
            formfield.widget.can_change_related = False
            formfield.widget.can_delete_related = False
        return formfield
    
    def has_add_permission(self, request):
        """Only one config instance allowed."""
        return not RentalConfig.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of config."""
        return False
