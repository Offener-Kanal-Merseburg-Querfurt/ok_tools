from .forms import InspectionInlineForm
from .models import AuditLog
from .models import Inspection
from .models import InspectionImport
from .models import InventoryImport
from .models import InventoryItem
from .models import Location
from .models import Manufacturer
from .models import Organization
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin import RelatedOnlyFieldListFilter
from django.utils.html import format_html
from django.utils.translation import gettext as _
from import_export.admin import ExportMixin
from import_export.fields import Field
from import_export.resources import ModelResource
from import_export.widgets import DateWidget


class InventoryResource(ModelResource):
    """Resource for InventoryItem export/import."""

    inventory_number = Field(attribute='inventory_number', column_name=_('Inventory Number'))
    description = Field(attribute='description', column_name=_('Description'))
    serial_number = Field(attribute='serial_number', column_name=_('Serial Number'))
    manufacturer = Field(attribute='manufacturer__name', column_name=_('Manufacturer'))
    location = Field(attribute='location', column_name=_('Location'))
    quantity = Field(attribute='quantity', column_name=_('Quantity'))
    status = Field(attribute='status', column_name=_('Status'))
    owner = Field(attribute='owner__name', column_name=_('Owner'))
    inventory_number_owner = Field(attribute='inventory_number_owner', column_name=_('Inventory Number Owner'))

    purchase_date = Field(
        attribute='purchase_date',
        column_name=_('Purchase Date'),
        widget=DateWidget(format='%Y-%m-%d')
    )

    class Meta:
        """Meta options for InventoryResource."""

        model = InventoryItem
        fields = (
            'inventory_number',
            'description',
            'serial_number',
            'manufacturer',
            'location',
            'quantity',
            'status',
            # 'object_type',
            'owner',
            'inventory_number_owner',
            'purchase_date',
            'purchase_cost'
        )


class InspectionInline(admin.TabularInline):
    """Inline admin for Inspection model."""

    model = Inspection
    form = InspectionInlineForm
    extra = 1
    fields = ("inspection_number", "target_part", "inspection_date", "result")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """Admin interface for Location (hierarchical)."""

    list_display = ("full_path", "parent")
    search_fields = ("name",)
    autocomplete_fields = ("parent",)
    ordering = ("parent__id", "name")


@admin.register(InventoryItem)
class InventoryItemAdmin(ExportMixin, admin.ModelAdmin):
    """Admin interface for InventoryItem."""

    change_list_template = 'admin/inventory_item_change_list.html'
    resource_class = InventoryResource
    readonly_fields = ('reserved_quantity', 'rented_quantity')
    list_display = (
        'inventory_number', 'description', 'serial_number', 'manufacturer', 'location', 'quantity',
        'status', 'owner', 'inventory_number_owner', 'available_for_rent'
    )
    search_fields = [
        'inventory_number', 'description', 'serial_number',
        'manufacturer__name', 'owner__name', 'inventory_number_owner',
        'location__name',
    ]
    list_filter = [
        AutocompleteFilterFactory(_('Manufacturer'), 'manufacturer'),
        AutocompleteFilterFactory(_('Owner'), 'owner'),
        AutocompleteFilterFactory(_('Location'), 'location'),
        ('purchase_date', admin.DateFieldListFilter),
        'status', 'available_for_rent',
    ]
    fields = (
        'inventory_number', 'description', 'serial_number', 'manufacturer', 'location', 'quantity',
        'status', 'owner', 'inventory_number_owner', 'purchase_date', 'purchase_cost',
        'available_for_rent', 'reserved_quantity', 'rented_quantity'
    )
    autocomplete_fields = ('manufacturer', 'owner', 'location')
    inlines = [InspectionInline]

    def get_readonly_fields(self, request, obj=None):
        """Return readonly fields depending on item status."""
        if obj and obj.status == InventoryItem.STATUS_RENTED:
            return self.readonly_fields + ('status',)
        return self.readonly_fields

    def get_form(self, request, obj=None, **kwargs):
        """Customize form fields for InventoryItem."""
        form = super().get_form(request, obj, **kwargs)
        if 'status' in form.base_fields:
            if not (obj and obj.status == InventoryItem.STATUS_RENTED):
                original_choices = form.base_fields['status'].choices
                form.base_fields['status'].choices = [
                    choice for choice in original_choices if choice[0] != InventoryItem.STATUS_RENTED
                ]
        return form


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    """Admin interface for Manufacturer."""

    list_display = ('name', 'description')
    search_fields = ['name', 'description']
    ordering = ['name']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin interface for Organization."""

    list_display = ('name', 'description')
    search_fields = ['name', 'description']
    ordering = ['name']


class AuditLogResource(ModelResource):
    """Resource for AuditLog export/import."""

    model_name = Field(attribute='model_name', column_name=_('Model Name'))
    object_id = Field(attribute='object_id', column_name=_('Object ID'))
    action = Field(attribute='action', column_name=_('Action'))
    changes = Field(attribute='changes', column_name=_('Changes'))
    timestamp = Field(attribute='timestamp', column_name=_('Timestamp'))

    class Meta:
        """Meta options for AuditLogResource."""

        model = AuditLog
        fields = []


@admin.register(AuditLog)
class AuditLogAdmin(ExportMixin, admin.ModelAdmin):
    """Admin interface for AuditLog."""

    resource_class = AuditLogResource
    list_display = (
        'get_inventory_number',
        'action',
        'get_changes_display',
        'user',
        'timestamp'
    )
    list_filter = (
        'action',
        ('user', RelatedOnlyFieldListFilter),
    )
    search_fields = ('object_id', 'changes')
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']
    list_per_page = 500
    show_full_result_count = False

    def get_inventory_number(self, obj):
        """Return inventory number for AuditLog."""
        return obj.get_inventory_number()
    get_inventory_number.short_description = _('Inventory Number')
    get_inventory_number.admin_order_field = 'object_id'

    def get_changes_display(self, obj):
        """Return changes display for AuditLog."""
        return obj.get_changes_display()
    get_changes_display.short_description = _('Changes')


@admin.register(InventoryImport)
class InventoryImportAdmin(admin.ModelAdmin):
    """Admin interface for InventoryImport."""

    change_form_template = 'admin/inventory_import_change_form.html'
    list_display = ('__str__', 'import_status', 'items_created', 'items_skipped', 'import_date', 'completed_date')
    readonly_fields = (
        'import_status',
        'items_created',
        'items_skipped',
        'get_error_log_display',
        'import_date',
        'completed_date'
    )
    exclude = ('error_log_file', 'error_log')
    ordering = ['-import_date']
    actions = ['import_files']

    def get_import_status_display(self, obj):
        """Return import status with icon."""
        status_icons = {
            'pending': '⏳',
            'in_progress': '🔄',
            'completed': '✅',
            'completed_with_errors': '⚠️',
            'failed': '❌'
        }
        return f"{status_icons.get(obj.import_status, '')} {obj.get_import_status_display()}"
    get_import_status_display.short_description = _('Status')

    def get_error_log_display(self, obj):
        """Return error log as HTML list with download link."""
        if not obj.error_log:
            return _('-')
        errors = obj.error_log.split('\n')
        error_list = ''.join(f'<li>{error}</li>' for error in errors)
        download_link = ''
        if obj.error_log_file:
            download_link = format_html(
                '<div style="margin-top: 10px;"><a href="{}" class="button" target="_blank">{}</a></div>',
                obj.error_log_file.url,
                _('Download Error Log File')
            )
        return format_html(
            '<div style="max-height: 300px; overflow-y: auto; '
            'border: 1px solid #ccc; background: #fafafa; padding: 8px;">'
            '<ul style="margin:0; padding-left:20px;">{}</ul></div>{}',
            format_html(error_list),
            download_link
        )
    get_error_log_display.short_description = _('Error Log')

    @admin.action(description=_('Import selected inventory files'))
    def import_files(self, request, queryset):
        """Import selected inventory files."""
        for import_obj in queryset:
            try:
                import_obj.import_data(request)
            except Exception as e:
                self.message_user(request, f'Error importing {import_obj.file.name}: {str(e)}', level=messages.ERROR)


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    """Admin interface for Inspection model."""

    list_display = ("inspection_number", "inventory_item", "target_part", "inspection_date", "result")
    search_fields = ("inspection_number", "inventory_item__inventory_number")
    list_filter = ("target_part",)


@admin.register(InspectionImport)
class InspectionImportAdmin(admin.ModelAdmin):
    """Admin interface for InspectionImport."""

    change_form_template = 'admin/inspection_import_change_form.html'
    list_display = ('__str__', 'import_status', 'items_created', 'items_skipped', 'import_date', 'completed_date')
    readonly_fields = (
        'import_status',
        'items_created',
        'items_skipped',
        'get_error_log_display',
        'import_date',
        'completed_date'
    )
    exclude = ('error_log_file', 'error_log')
    ordering = ['-import_date']
    actions = ['import_files']

    def get_import_status_display(self, obj):
        """Return import status with icon."""
        status_icons = {
            'pending': '⏳',
            'in_progress': '🔄',
            'completed': '✅',
            'completed_with_errors': '⚠️',
            'failed': '❌'
        }
        return f"{status_icons.get(obj.import_status, '')} {obj.get_import_status_display()}"
    get_import_status_display.short_description = _('Status')

    def get_error_log_display(self, obj):
        """Return error log as HTML list with download link."""
        if not obj.error_log:
            return _('-')
        errors = obj.error_log.split('\n')
        error_list = ''.join(f'<li>{error}</li>' for error in errors)
        download_link = ''
        if obj.error_log_file:
            download_link = format_html(
                '<div style="margin-top: 10px;"><a href="{}" class="button" target="_blank">{}</a></div>',
                obj.error_log_file.url,
                _('Download Error Log File')
            )
        return format_html(
            '<div style="max-height: 300px; overflow-y: auto; '
            'border: 1px solid #ccc; background: #fafafa; padding: 8px;">'
            '<ul style="margin:0; padding-left:20px;">{}</ul></div>{}',
            format_html(error_list),
            download_link
        )
    get_error_log_display.short_description = _('Error Log')

    @admin.action(description=_('Import selected inspection files'))
    def import_files(self, request, queryset):
        """Import selected inspection files."""
        for import_obj in queryset:
            try:
                import_obj.import_data(request)
            except Exception as e:
                self.message_user(request, f'Error importing {import_obj.file.name}: {str(e)}', level=messages.ERROR)
