from django.core.management.base import BaseCommand
from inventory.models import Inspection
from inventory.models import InventoryItem


class Command(BaseCommand):
    """Django management command to link unbound inspections to inventory items by inventory_number."""

    help = "Link unbound inspections to inventory items by inventory_number."

    def handle(self, *args, **options):
        """Handle the link command."""
        linked = 0
        unlinked = Inspection.objects.filter(inventory_item__isnull=True).exclude(inventory_number="")
        for insp in unlinked:
            item = InventoryItem.objects.filter(inventory_number=insp.inventory_number).first()
            if item:
                insp.inventory_item = item
                insp.save(update_fields=["inventory_item"])
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Linked {linked} inspection(s)."))
