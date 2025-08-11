from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from inventory.models import Location


class Command(BaseCommand):
    """Import locations from a file, one hierarchical path per line."""

    help = "Import locations from a text/CSV file, one path per line (e.g. 'Комната 1 -> Шкаф 2')."

    def add_arguments(self, parser):
        """Register CLI arguments for the command."""
        parser.add_argument('--file', required=True, help='Path to file with location paths')

    def handle(self, *args, **options):
        """Execute the import logic."""
        path = options['file']
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception as e:
            raise CommandError(str(e))

        created = 0
        for line in lines:
            loc = Location.objects.get_by_path(line)
            if loc is None:
                Location.objects.create_by_path(line)
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} new locations."))
