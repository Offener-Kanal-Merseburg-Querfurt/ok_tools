from .views import AccessDeniedView
from .views import BarcodePrintView
from .views import CreateSigningSessionView
from .views import EquipmentSetItemViewSet
from .views import EquipmentSetViewSet
from .views import InventoryItemViewSet
from .views import PrintFormView
from .views import PrintPickListView
from .views import RentalDetailView
from .views import UserRentalDetailView
from .views import RentalIssueViewSet
from .views import RentalItemViewSet
from .views import RentalProcessView
from .views import RentalReturnView
from .views import RentalReturnWorkflowView
from .views import RentalRequestViewSet
from .views import EquipmentSetsAdminView
from .views import RentalStatsView
from .views import SaveSignatureView
from .views import SigningSessionPageView
from .views import SigningSessionQRCodeView
from .views import SigningSessionStatusView
from .views import SubmitSigningSessionView
from .views import InventoryCalendarDayView
from .views import InventoryCalendarWeekView
from .views import RoomCalendarDayView
from .views import RoomCalendarMonthView
from .views import RoomCalendarWeekView
from .views import RentalListView
from .views import api_inventory_calendar
from .views import RentalTransactionViewSet
from .views import cancel_rental
from .views import close_rental
from .views import create_submit
from .views import duplicate_rental
from .views import MissingConsumablesView
from .views import add_rental_consumables
from .views import delete_rental_consumable
from .views import edit_note
from .views import resolve_rental_consumable
from .views import update_rental_consumable
from .views import extend_rental
from .views import mark_issued
from .views import print_form_msa_redirect
from .views import print_form_okmq_redirect
from .views import serve_room_image
from .views import print_slip
from .views import quick_issue
from .views import remove_item_from_rental
from .views import reopen_rental
from .views import report_issue
from .views import send_reminder
from .views import swap_rental_item
from .views import api_barcode_lookup
from .views import api_cancel_rental
from .views import api_print_labels
from .views import api_confirm_rental
from .views import api_check_room_availability
from .views import api_create_equipment_set
from .views import api_create_rental
from .views import api_create_rental_user
from .views import api_delete_equipment_set
from .views import api_delete_template
from .views import api_expire_room_rentals
from .views import api_extend_rental
from .views import api_get_all_equipment_sets
from .views import api_get_all_inventory_status
from .views import api_get_all_rentals
from .views import api_get_equipment_set_details
from .views import api_get_equipment_set_details_user
from .views import api_get_equipment_sets
from .views import api_get_equipment_sets_user
from .views import api_get_filter_options
from .views import api_get_filter_options_user
from .views import api_get_inventory_schedule
from .views import api_get_rental_print_info
from .views import api_get_room_schedule
from .views import api_get_room_schedule_user
from .views import api_get_rooms
from .views import api_get_rooms_user
from .views import api_get_staff_users
from .views import api_get_templates
from .views import api_get_user_inventory
from .views import api_get_user_inventory_simple
from .views import api_get_user_rental_details
from .views import api_get_user_rental_details_by_id
from .views import api_get_user_stats
from .views import api_issue_from_reservation
from .views import api_load_template
from .views import api_reset_rental_system
from .views import api_return_items
from .views import api_return_rental_items
from .views import api_save_template
from .views import api_scan_return_item
from .views import api_search_inventory_items
from .views import api_search_users
from .views import api_user_active_items
from .views import api_update_pick_list
from .views_api import api_availability_check
from .views_api import api_add_rental_items
from .views_api import api_add_room_to_rental
from .views_api import api_change_rental_period
from .views_api import api_change_rental_user
from .views_api import api_inventory_search
from .views_api import api_remove_room_rental
from .views_api import api_update_room_rental
from .views_api import api_users_search
from .email_approval_views import email_approval_action
from django.urls import include
from django.urls import path
from rest_framework.routers import DefaultRouter


app_name = "rental"

router = DefaultRouter()
router.register(r'inventory-items', InventoryItemViewSet, basename='inventory-item')
router.register(r'rental-requests', RentalRequestViewSet, basename='rental-request')
router.register(r'rental-items', RentalItemViewSet, basename='rental-item')
router.register(r'rental-transactions', RentalTransactionViewSet, basename='rental-transaction')
router.register(r'rental-issues', RentalIssueViewSet, basename='rental-issue')
router.register(r'equipment-sets', EquipmentSetViewSet, basename='equipment-set')
router.register(r'equipment-set-items', EquipmentSetItemViewSet, basename='equipment-set-item')

urlpatterns = [
    path('admin/', RentalListView.as_view(), name='list'),
    path('admin/return/', RentalReturnWorkflowView.as_view(), name='admin_return'),
    path('new/', RentalProcessView.as_view(), name='create'),
    path('create/submit/', create_submit, name='create_submit'),
    path('quick-issue/', quick_issue, name='quick_issue'),
    path('api/', include(router.urls)),
    # Custom admin-like pages and endpoints
    path('admin/rental-process/', RentalProcessView.as_view(), name='admin_rental_process'),
    path('admin/stats/', RentalStatsView.as_view(), name='rental_stats'),
    path('admin/equipment-sets/', EquipmentSetsAdminView.as_view(), name='admin_equipment_sets'),
    path('admin/inventory-calendar/day/', InventoryCalendarDayView.as_view(), name='inventory_calendar_day'),
    path('admin/inventory-calendar/week/', InventoryCalendarWeekView.as_view(), name='inventory_calendar_week'),
    path('admin/room-calendar/day/', RoomCalendarDayView.as_view(), name='room_calendar_day'),
    path('admin/room-calendar/week/', RoomCalendarWeekView.as_view(), name='room_calendar_week'),
    path('admin/room-calendar/month/', RoomCalendarMonthView.as_view(), name='room_calendar_month'),
    path('admin/room-calendar/week/', RoomCalendarWeekView.as_view(), name='room_calendar_week'),
    path('admin/room-calendar/month/', RoomCalendarMonthView.as_view(), name='room_calendar_month'),
    path('access-denied/', AccessDeniedView.as_view(), name='access_denied'),
    path('api/search-users/', api_search_users, name='api_search_users'),
    path('api/user/<int:user_id>/inventory/', api_get_user_inventory, name='api_user_inventory'),
    path('api/user/<int:user_id>/stats/', api_get_user_stats, name='api_user_stats'),
    path('api/create-rental/', api_create_rental, name='api_create_rental'),
    path('api/user/<int:user_id>/active-items/', api_user_active_items, name='api_user_active_items'),
    path('api/return-items/', api_return_items, name='api_return_items'),
    path('api/filter-options/', api_get_filter_options, name='api_filter_options'),
    path('api/equipment-sets/', EquipmentSetViewSet.as_view({'get': 'list', 'post': 'create'}), name='api_equipment_sets'),
    path('api/equipment-sets/<int:pk>/', EquipmentSetViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='api_equipment_set_detail'),
    path('api/equipment-sets-available/', api_get_equipment_sets, name='api_equipment_sets_available'),
    path('api/equipment-set/<int:set_id>/details/', api_get_equipment_set_details, name='api_equipment_set_details'),
    path('api/delete-equipment-set/<int:pk>/', api_delete_equipment_set, name='api_delete_equipment_set'),

    # Rooms API
    path('api/rooms-available/', api_get_rooms, name='api_rooms_available'),
    path('api/room-schedule/', api_get_room_schedule, name='api_room_schedule'),
    path('api/inventory-schedule/', api_get_inventory_schedule, name='api_inventory_schedule'),
    path('api/user/<int:user_id>/rental-details/', api_get_user_rental_details_by_id, name='api_user_rental_details'),
    path('api/rental-details/', api_get_user_rental_details, name='api_rental_details'),
    path('api/cancel-rental/', api_cancel_rental, name='api_cancel_rental'),
    path('api/confirm-rental/', api_confirm_rental, name='api_confirm_rental'),
    path('api/extend-rental/', api_extend_rental, name='api_extend_rental'),
    path('api/issue-from-reservation/', api_issue_from_reservation, name='api_issue_from_reservation'),
    path('api/get-staff-users/', api_get_staff_users, name='api_get_staff_users'),
    path('api/return-rental-items/', api_return_rental_items, name='api_return_rental_items'),
    path('api/save-template/', api_save_template, name='api_save_template'),
    path('api/get-templates/', api_get_templates, name='api_get_templates'),
    path('api/load-template/<int:template_id>/', api_load_template, name='api_load_template'),
    path('api/delete-template/<int:template_id>/', api_delete_template, name='api_delete_template'),

    # Stats API endpoints
    path('api/reset-rental-system/', api_reset_rental_system, name='api_reset_rental_system'),
    path('api/get-all-rentals/', api_get_all_rentals, name='api_get_all_rentals'),
    path('api/get-all-inventory-status/', api_get_all_inventory_status, name='api_get_all_inventory_status'),
    path('api/get-all-equipment-sets/', api_get_all_equipment_sets, name='api_get_all_equipment_sets'),
    path('api/inventory-calendar/', api_inventory_calendar, name='api_inventory_calendar'),
    path('api/create-equipment-set/', api_create_equipment_set, name='api_create_equipment_set'),
    path('api/search-inventory/', api_search_inventory_items, name='api_search_inventory'),
    path('api/barcode/lookup/', api_barcode_lookup, name='api_barcode_lookup'),
    path('api/scan-return/', api_scan_return_item, name='api_scan_return_item'),
    path('api/rental/inventory/', api_inventory_search, name='api_inventory_search'),
    path('api/rental/users/', api_users_search, name='api_users_search'),
    path('api/rental/check-availability/', api_availability_check, name='api_availability_check'),
    path('api/rental/<int:rental_id>/pick-list/', api_update_pick_list, name='api_update_pick_list'),

    # Room expiration API
    path('api/expire-room-rentals/', api_expire_room_rentals, name='api_expire_room_rentals'),

    # User-accessible API endpoints (without staff requirement)
    path('api/user/filter-options/', api_get_filter_options_user, name='api_filter_options_user'),
    path('api/user/<int:user_id>/inventory-simple/', api_get_user_inventory_simple, name='api_user_inventory_simple'),
    path('api/user/equipment-sets/', api_get_equipment_sets_user, name='api_equipment_sets_user'),
    path('api/user/equipment-set/<int:set_id>/details/', api_get_equipment_set_details_user, name='api_equipment_set_details_user'),
    path('api/user/rooms/', api_get_rooms_user, name='api_rooms_user'),
    path('api/user/create-rental/', api_create_rental_user, name='api_create_rental_user'),
    path('api/user/room-schedule/', api_get_room_schedule_user, name='api_room_schedule_user'),
    path('api/user/rental-details/', api_get_user_rental_details, name='api_user_rental_details'),
    path('api/user/check-room-availability/', api_check_room_availability, name='api_check_room_availability'),

    # Detail page for rental
    path('rental/<int:rental_id>/', RentalDetailView.as_view(), name='rental_detail'),
    path('admin/return/<int:rental_id>/', RentalReturnView.as_view(), name='rental_return'),
    path('rental/<int:rental_id>/extend/', extend_rental, name='extend'),
    path('rental/<int:rental_id>/mark-issued/', mark_issued, name='mark_issued'),
    path('rental/<int:rental_id>/cancel/', cancel_rental, name='cancel'),
    path('rental/<int:rental_id>/reopen/', reopen_rental, name='reopen'),
    path('rental/<int:rental_id>/remove-item/', remove_item_from_rental, name='remove_item'),
    path('rental/<int:rental_id>/swap-item/', swap_rental_item, name='swap_item'),
    path('rental/<int:rental_id>/close/', close_rental, name='close'),
    path('rental/<int:rental_id>/send-reminder/', send_reminder, name='send_reminder'),
    path('rental/<int:rental_id>/edit-note/', edit_note, name='edit_note'),
    path('rental/<int:rental_id>/consumables/add/', add_rental_consumables, name='add_consumables'),
    path('rental/<int:rental_id>/consumables/<int:consumable_id>/delete/',
         delete_rental_consumable, name='delete_consumable'),
    path('rental/<int:rental_id>/consumables/<int:consumable_id>/update/',
         update_rental_consumable, name='update_consumable'),
    path('rental/<int:rental_id>/consumables/<int:consumable_id>/resolve/',
         resolve_rental_consumable, name='resolve_consumable'),
    path('admin/missing-consumables/', MissingConsumablesView.as_view(), name='missing_consumables'),
    path('rental/<int:rental_id>/report-issue/', report_issue, name='report_issue'),
    path('rental/<int:rental_id>/duplicate/', duplicate_rental, name='duplicate'),
    path('rental/<int:rental_id>/print-slip/', print_slip, name='print_slip'),
    # User detail page for rental
    path('user/rental/<int:rental_id>/', UserRentalDetailView.as_view(), name='user_rental_detail'),

    # Print forms
    path('print/<int:org_id>/<int:rental_id>/', PrintFormView.as_view(), name='print_form'),
    path('print/msa/<int:rental_id>/', print_form_msa_redirect, name='print_form_msa'),
    path('print/okmq/<int:rental_id>/', print_form_okmq_redirect, name='print_form_okmq'),
    path('print/pick-list/<int:rental_id>/', PrintPickListView.as_view(), name='print_pick_list'),
    path('barcode/print/', BarcodePrintView.as_view(), name='barcode_print'),
    path('barcode/print-direct/', api_print_labels, name='barcode_print_direct'),
    path('room-image/<int:image_id>/', serve_room_image, name='room_image'),
    path('api/rental/<int:rental_id>/print-info/', api_get_rental_print_info, name='api_rental_print_info'),

    # Signature URLs
    path('rental/<int:pk>/save-signature/', SaveSignatureView.as_view(), name='save_signature'),
    path('rental/<int:pk>/sign-session/create/', CreateSigningSessionView.as_view(), name='create_sign_session'),
    path('rental/<int:rental_id>/change-user/', api_change_rental_user, name='api_change_rental_user'),
    path('rental/<int:rental_id>/change-period/', api_change_rental_period, name='api_change_rental_period'),
    path('rental/<int:rental_id>/add-items/', api_add_rental_items, name='api_add_rental_items'),
    path('rental/<int:rental_id>/add-room/', api_add_room_to_rental, name='api_add_room_to_rental'),
    path('rental/<int:rental_id>/update-room-rental/', api_update_room_rental, name='api_update_room_rental'),
    path('rental/<int:rental_id>/remove-room-rental/', api_remove_room_rental, name='api_remove_room_rental'),
    path('sign-session/<str:token>/status/', SigningSessionStatusView.as_view(), name='sign_session_status'),
    path('sign-session/<str:token>/qr/', SigningSessionQRCodeView.as_view(), name='sign_session_qr'),
    path('sign-session/<str:token>/', SigningSessionPageView.as_view(), name='sign_session_page'),
    path('sign-session/<str:token>/submit/', SubmitSigningSessionView.as_view(), name='sign_session_submit'),

    # Email approval (signed links)
    path('email-approval/<int:rental_id>/<str:action>/<str:token>/', email_approval_action, name='email_approval_action'),
]
