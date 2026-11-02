"""
Email notifications for rental lifecycle events.

All strings use Django i18n; translation.activate('de') is called before render.
"""

from __future__ import annotations
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from registration.email import send_mail
import logging


logger = logging.getLogger('django')


def _get_org_context():
    from registration.organization_config import get_organization_address
    from registration.organization_config import get_organization_email
    from registration.organization_config import get_organization_name
    from registration.organization_config import get_organization_phone
    from registration.organization_config import get_organization_website
    return {
        'ok_email': get_organization_email(),
        'ok_phone': get_organization_phone(),
        'ok_address': get_organization_address(),
        'ok_website': get_organization_website(),
        'ok_name': get_organization_name(),
    }


def send_issued_confirmation_email(*, rental_request) -> None:
    user_email = getattr(rental_request.user, "email", None)
    if not user_email:
        logger.warning("No email for user %s, skipping issued confirmation (rental_id=%s)", rental_request.user.pk, rental_request.id)
        return

    contact_email = getattr(settings, "OK_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", "") or ""

    items = []
    for item in rental_request.items.select_related("inventory_item").all():
        items.append({"name": str(item.inventory_item), "quantity": item.quantity_requested})

    rooms = []
    for room_rental in rental_request.room_rentals.select_related("room").all():
        rooms.append({"name": room_rental.room.name, "people_count": room_rental.people_count, "start": room_rental.get_start_date(), "end": room_rental.get_end_date()})

    user_name = _get_user_display_name(rental_request.user)
    context = {
        **_get_org_context(),
        "rental_id": rental_request.id,
        "user_name": user_name,
        "project_name": rental_request.project_name,
        "purpose": rental_request.purpose,
        "start": rental_request.requested_start_date,
        "end": rental_request.requested_end_date,
        "actual_start": rental_request.actual_start_date,
        "items": items,
        "rooms": rooms,
        "items_total": rental_request.total_items_count,
        "rooms_total": rental_request.total_rooms_count,
        "contact_email": contact_email,
    }

    from_email = getattr(settings, "EMAIL_HOST_USER", "")

    translation.activate('de')
    try:
        send_mail(
            subject_template_name="email/rental_request_issued_subject.txt",
            email_template_name="email/rental_request_issued_body.txt",
            html_email_template_name="email/rental_request_issued_body.html",
            context=context,
            from_email=from_email,
            to_email=user_email,
        )
        logger.info("Issued confirmation sent to %s (rental_id=%s)", user_email, rental_request.id)
    except Exception:
        logger.exception("Failed to send issued confirmation to %s (rental_id=%s)", user_email, rental_request.id)
    finally:
        translation.deactivate()


def send_reminder_email(*, rental_request) -> bool:
    user_email = getattr(rental_request.user, "email", None)
    if not user_email:
        logger.warning("No email for user %s, skipping reminder (rental_id=%s)", rental_request.user.pk, rental_request.id)
        return False

    contact_email = getattr(settings, "OK_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", "") or ""

    items = []
    for item in rental_request.items.select_related("inventory_item").all():
        items.append({"name": str(item.inventory_item), "quantity": item.quantity_requested})

    rooms = []
    for room_rental in rental_request.room_rentals.select_related("room").all():
        rooms.append({"name": room_rental.room.name, "people_count": room_rental.people_count, "start": room_rental.get_start_date(), "end": room_rental.get_end_date()})

    is_issued = rental_request.status == 'issued'
    user_name = _get_user_display_name(rental_request.user)
    context = {
        **_get_org_context(),
        "rental_id": rental_request.id,
        "user_name": user_name,
        "project_name": rental_request.project_name,
        "start": rental_request.requested_start_date,
        "end": rental_request.requested_end_date,
        "actual_start": rental_request.actual_start_date,
        "status": rental_request.get_status_display(),
        "is_issued": is_issued,
        "items": items,
        "rooms": rooms,
        "items_total": len(items),
        "rooms_total": len(rooms),
        "contact_email": contact_email,
    }

    from_email = getattr(settings, "EMAIL_HOST_USER", "")
    subject_tmpl = "email/rental_request_reminder_subject.txt" if is_issued else "email/rental_request_issued_subject.txt"
    body_tmpl = "email/rental_request_reminder_body.txt" if is_issued else "email/rental_request_issued_body.txt"
    html_tmpl = "email/rental_request_reminder_body.html" if is_issued else "email/rental_request_issued_body.html"

    translation.activate('de')
    try:
        attachments = _build_print_form_attachment(rental_request) if is_issued else None
        send_mail(
            subject_template_name=subject_tmpl,
            email_template_name=body_tmpl,
            html_email_template_name=html_tmpl,
            context=context,
            from_email=from_email,
            to_email=user_email,
            attachments=attachments,
        )
        logger.info("Reminder sent to %s (rental_id=%s, status=%s)", user_email, rental_request.id, rental_request.status)
        return True
    except Exception:
        logger.exception("Failed to send reminder to %s (rental_id=%s)", user_email, rental_request.id)
        return False
    finally:
        translation.deactivate()


def send_return_receipt_email(*, rental_request, returned_items=None, note='', missing_items=None) -> None:
    user_email = getattr(rental_request.user, "email", None)
    if not user_email:
        logger.warning("No email for user %s, skipping return receipt (rental_id=%s)", rental_request.user.pk, rental_request.id)
        return

    contact_email = getattr(settings, "OK_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", "") or ""
    context = {
        "ok_name": getattr(settings, "OK_NAME", ""),
        "rental_id": rental_request.id,
        "user_name": rental_request.user.get_full_name() or rental_request.user.email,
        "project_name": rental_request.project_name,
        "returned_at": rental_request.actual_end_date,
        "returned_items": returned_items or [],
        "missing_items": missing_items or [],
        "note": note,
        "contact_email": contact_email,
    }

    from_email = getattr(settings, "EMAIL_HOST_USER", "")

    translation.activate('de')
    try:
        send_mail(
            subject_template_name="email/rental_return_receipt_subject.txt",
            email_template_name="email/rental_return_receipt_body.txt",
            html_email_template_name="email/rental_return_receipt_body.html",
            context=context,
            from_email=from_email,
            to_email=user_email,
        )
        logger.info("Return receipt sent to %s (rental_id=%s)", user_email, rental_request.id)
    except Exception:
        logger.exception("Failed to send return receipt to %s (rental_id=%s)", user_email, rental_request.id)
    finally:
        translation.deactivate()


def send_missing_consumables_reminder_email(*, user, consumables) -> bool:
    """Remind ``user`` about consumables from their rentals that are still missing."""
    user_email = getattr(user, "email", None)
    if not user_email:
        logger.warning("No email for user %s, skipping missing consumables reminder", user.pk)
        return False

    contact_email = getattr(settings, "OK_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", "") or ""
    context = {
        **_get_org_context(),
        "user_name": _get_user_display_name(user),
        "items": [
            {
                "name": consumable.name,
                "quantity": consumable.quantity_missing,
                "rental_id": consumable.rental_request_id,
                "project_name": consumable.rental_request.project_name,
            }
            for consumable in consumables
        ],
        "contact_email": contact_email,
    }

    translation.activate('de')
    try:
        send_mail(
            subject_template_name="email/rental_missing_consumables_subject.txt",
            email_template_name="email/rental_missing_consumables_body.txt",
            html_email_template_name="email/rental_missing_consumables_body.html",
            context=context,
            from_email=getattr(settings, "EMAIL_HOST_USER", ""),
            to_email=user_email,
        )
        logger.info("Missing consumables reminder sent to %s (%s item(s))", user_email, len(context["items"]))
        return True
    except Exception:
        logger.exception("Failed to send missing consumables reminder to %s", user_email)
        return False
    finally:
        translation.deactivate()


def _build_print_form_attachment(rental_request):
    from django.template.loader import render_to_string

    attachments = []
    all_items = rental_request.items.select_related('inventory_item__owner', 'inventory_item__location')

    has_msa = False
    has_non_msa = False
    msa_org_id = None
    for item in all_items:
        owner = item.inventory_item.owner
        if owner and owner.name == 'MSA':
            has_msa = True
            msa_org_id = owner.id
        else:
            has_non_msa = True

    context = {
        'rental_request': rental_request,
        'has_signature': rental_request.has_any_signature(),
        'signature_image': rental_request.signature,
        'signature_signed_at': rental_request.signature_signed_at,
        'signature_method': rental_request.signature_method,
    }

    static_root = getattr(settings, 'STATIC_ROOT', '/app/staticfiles')

    if has_non_msa or not has_msa:
        try:
            from weasyprint import HTML
            ctx = {**context, 'items': all_items, 'okmq_items': all_items}
            html = render_to_string('rental/print_form_okmq.html', ctx)
            html = html.replace('/static/', f'file://{static_root}/')
            pdf = HTML(string=html).write_pdf()
            attachments.append((f'Ausleihe_{rental_request.id}.pdf', pdf, 'application/pdf'))
        except Exception as e:
            logger.exception('Failed to generate OKMQ PDF for rental %s: %s', rental_request.id, e)

    if has_msa:
        try:
            from weasyprint import HTML
            msa_items = all_items.filter(inventory_item__owner_id=msa_org_id) if msa_org_id else all_items
            ctx = {**context, 'items': msa_items, 'msa_items': msa_items}
            html = render_to_string('rental/print_form_msa.html', ctx)
            html = html.replace('/static/', f'file://{static_root}/')
            pdf = HTML(string=html).write_pdf()
            attachments.append((f'MSA_Ausleihe_{rental_request.id}.pdf', pdf, 'application/pdf'))
        except Exception as e:
            logger.exception('Failed to generate MSA PDF for rental %s: %s', rental_request.id, e)

    return attachments if attachments else None


def _get_user_display_name(user):
    profile = getattr(user, 'profile', None)
    if profile:
        first = getattr(profile, 'first_name', '') or ''
        last = getattr(profile, 'last_name', '') or ''
        if first or last:
            return f'{first} {last}'.strip()
    full = user.get_full_name()
    if full and full != user.email:
        return full
    return user.email or str(user)
