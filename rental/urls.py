from .views import AccessDeniedView
from .views import EquipmentSetItemViewSet
from .views import EquipmentSetViewSet
from .views import InventoryItemViewSet
from .views import PrintFormMSAView
from .views import PrintFormOKMQView
from .views import RentalDetailView
from .views import RentalIssueViewSet
from .views import RentalItemViewSet
from .views import RentalProcessView
from .views import RentalRequestViewSet
from .views import RentalStatsView
from .views import RentalTransactionViewSet
from .views import api_cancel_rental
from .views import api_check_room_availability
from .views import api_create_equipment_set
from .views import api_create_rental
from .views import api_create_rental_user
from .views import api_delete_equipment_set
from .views import api_expire_room_rentals
from .views import api_extend_rental
from .views import api_get_all_equipment_sets
from .views import api_get_all_inventory_status
from .views import api_get_all_rentals
from .views import api_get_equipment_set_details
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
from .views import api_get_user_inventory
from .views import api_get_user_inventory_simple
from .views import api_get_user_rental_details
from .views import api_get_user_rental_details_by_id
from .views import api_get_user_stats
from .views import api_issue_from_reservation
from .views import api_reset_rental_system
from .views import api_return_items
from .views import api_return_rental_items
from .views import api_search_inventory_items
from .views import api_search_users
from .views import api_user_active_items
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
    path('api/', include(router.urls)),
    # Custom admin-like pages and endpoints
    path('admin/rental-process/', RentalProcessView.as_view(), name='admin_rental_process'),
    path('admin/stats/', RentalStatsView.as_view(), name='rental_stats'),
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
    path('api/extend-rental/', api_extend_rental, name='api_extend_rental'),
    path('api/issue-from-reservation/', api_issue_from_reservation, name='api_issue_from_reservation'),
    path('api/get-staff-users/', api_get_staff_users, name='api_get_staff_users'),
    path('api/return-rental-items/', api_return_rental_items, name='api_return_rental_items'),

    # Stats API endpoints
    path('api/reset-rental-system/', api_reset_rental_system, name='api_reset_rental_system'),
    path('api/get-all-rentals/', api_get_all_rentals, name='api_get_all_rentals'),
    path('api/get-all-inventory-status/', api_get_all_inventory_status, name='api_get_all_inventory_status'),
    path('api/get-all-equipment-sets/', api_get_all_equipment_sets, name='api_get_all_equipment_sets'),
    path('api/create-equipment-set/', api_create_equipment_set, name='api_create_equipment_set'),
    path('api/search-inventory/', api_search_inventory_items, name='api_search_inventory'),

    # Room expiration API
    path('api/expire-room-rentals/', api_expire_room_rentals, name='api_expire_room_rentals'),

    # User-accessible API endpoints (without staff requirement)
    path('api/user/filter-options/', api_get_filter_options_user, name='api_filter_options_user'),
    path('api/user/<int:user_id>/inventory-simple/', api_get_user_inventory_simple, name='api_user_inventory_simple'),
    path('api/user/equipment-sets/', api_get_equipment_sets_user, name='api_equipment_sets_user'),
    path('api/user/rooms/', api_get_rooms_user, name='api_rooms_user'),
    path('api/user/create-rental/', api_create_rental_user, name='api_create_rental_user'),
    path('api/user/room-schedule/', api_get_room_schedule_user, name='api_room_schedule_user'),
    path('api/user/rental-details/', api_get_user_rental_details, name='api_user_rental_details'),
    path('api/user/check-room-availability/', api_check_room_availability, name='api_check_room_availability'),

    # Detail page for rental
    path('rental/<int:rental_id>/', RentalDetailView.as_view(), name='rental_detail'),

    # Print forms
    path('print/msa/<int:rental_id>/', PrintFormMSAView.as_view(), name='print_form_msa'),
    path('print/okmq/<int:rental_id>/', PrintFormOKMQView.as_view(), name='print_form_okmq'),
    path('api/rental/<int:rental_id>/print-info/', api_get_rental_print_info, name='api_rental_print_info'),
]
