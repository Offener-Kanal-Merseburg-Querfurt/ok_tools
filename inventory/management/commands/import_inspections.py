from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from inventory.inspection_import import inspection_import
from pathlib import Path


class Command(BaseCommand):
    """Django management command to import or update inspections from a CSV or XLSX file."""

    help = "Import or update inspections from a CSV file."

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument("csv_file", type=str, help="Path to CSV or XLSX file (UTF-8)")

    def handle(self, *args, **options):
        """Handle the import command."""
        path = Path(options["csv_file"])
        if not path.exists():
            raise CommandError("File not found")
        with path.open("rb") as f:
            res = inspection_import(None, f, None)
        self.stdout.write(self.style.SUCCESS(
            f"Imported {res['created']} new and updated {res['skipped']} inspections."
        ))
