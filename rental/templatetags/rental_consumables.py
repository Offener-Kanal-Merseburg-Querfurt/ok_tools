"""Template helpers for consumables handed out with rentals."""

from django import template
from rental.models import RentalConsumable


register = template.Library()


@register.simple_tag
def missing_consumables_count():
    """Number of missing consumables, for the rental sidebar."""
    return RentalConsumable.objects.filter(status=RentalConsumable.STATUS_MISSING).count()
