from __future__ import annotations
from django.contrib import admin
from django.contrib.admin.sites import site as default_site
from django.urls import reverse
from django.utils.html import format_html
from typing import Any
from typing import Dict
from typing import List


# Custom order of models inside apps on Django admin index.
# Keys are app labels, values are lists of model class names in desired order.
ADMIN_MODEL_ORDER: Dict[str, List[str]] = {
    "inventory": [
        "InventoryItem",
        "Location",
        "InventoryImport",
        "Inspection",
        "InspectionImport",
        "Manufacturer",
        "Organization",
        "AuditLog",
    ],
    "rental": [
        "RentalProcessProxy",  # This will be the first item - our custom rental process link
        "Room",
        "EquipmentSet",
        "RentalIssue",
        "RentalItem",
        "RentalRequest",
        "RoomRental",
        "RentalTransaction",
    ],
}


def _reorder_app_list(app_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for app in app_list:
        desired = ADMIN_MODEL_ORDER.get(app.get("app_label"))
        if not desired:
            continue
        order_index = {name: idx for idx, name in enumerate(desired)}

        app["models"].sort(
            key=lambda m: (
                order_index.get(m.get("object_name"), 10_000),
                m.get("name", ""),
            )
        )
    return app_list


# Monkey-patch the existing default admin.site instance so all registrations remain valid
_original_get_app_list = default_site.get_app_list


def _custom_get_app_list(self: admin.AdminSite, request, app_label=None):  # type: ignore[override]
    app_list = list(_original_get_app_list(app_label=app_label, request=request))

    # Добавляем ссылку на дашборд в начало списка
    if app_label is None:  # Только на главной странице админки
        dashboard_app = {
            'name': 'Dashboard',
            'app_label': 'dashboard',
            'app_url': '/admin-dashboard/',
            'has_module_perms': True,
            'models': [
                {
                    'name': 'Main Dashboard',
                    'object_name': 'Dashboard',
                    'admin_url': '/admin-dashboard/',
                    'add_url': None,
                    'view_only': True,
                }
            ]
        }
        app_list.insert(0, dashboard_app)

    return _reorder_app_list(app_list)


default_site.get_app_list = _custom_get_app_list.__get__(default_site, admin.AdminSite)
