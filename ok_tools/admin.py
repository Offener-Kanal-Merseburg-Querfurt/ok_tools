from __future__ import annotations
from django.contrib import admin
from django.contrib.admin.sites import site as default_site
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
    return _reorder_app_list(app_list)


default_site.get_app_list = _custom_get_app_list.__get__(default_site, admin.AdminSite)


class SanitizeGetParamsMixin:
    """Mixin to normalize GET parameters for admin changelist.

    Some third-party filters (e.g., date range filters) or repeated query
    parameters may produce list values in request.GET. Django form fields
    expect strings and will call .strip(), which fails on lists.

    This mixin flattens list values to the last non-empty string before the
    parent changelist_view processes them.
    """

    @staticmethod
    def _flatten_querydict(querydict: Any) -> Any:
        try:
            qd = querydict.copy()
        except Exception:
            return querydict

        for key, values in qd.lists():
            if isinstance(values, list):
                # pick the last non-empty value; fallback to empty string
                flattened = next((v for v in reversed(values) if v not in (None, "")), "")
                qd.setlist(key, [flattened])
        return qd

    def changelist_view(self, request, extra_context=None):  # type: ignore[override]
        try:
            request.GET = self._flatten_querydict(request.GET)
        except Exception:
            # Fail-safe: proceed without modification
            pass
        return super().changelist_view(request, extra_context=extra_context)
