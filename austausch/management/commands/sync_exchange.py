"""Management command to manually sync exchange folders."""

from austausch.models import ExchangeConfig
from austausch.services.nextcloud_exchange_service import NextcloudExchangeService
from austausch.tasks import get_channels
from austausch.tasks import sync_exchange_folders_task
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Command to sync exchange folders manually."""
    
    help = 'Manually sync exchange folders from Nextcloud'

    def add_arguments(self, parser):
        parser.add_argument(
            '--discover', action='store_true',
            help='Only list the channels that would be synced, do not sync.')
        parser.add_argument(
            '--full', action='store_true',
            help='Scan all date folders, ignoring the age limits.')
    
    def handle(self, *args, **options):
        """Execute sync task."""
        if options['discover']:
            config = ExchangeConfig.get_config()
            channels = get_channels(config, NextcloudExchangeService(config))
            for channel, folder_path in sorted(channels.items()):
                self.stdout.write(f'{channel}: {folder_path}')
            self.stdout.write(f'{len(channels)} channel(s)')
            return

        self.stdout.write('Starting exchange folders sync...')
        
        try:
            sync_exchange_folders_task(full=options['full'])
            self.stdout.write(
                self.style.SUCCESS('Successfully synced exchange folders')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error syncing exchange folders: {e}')
            )
            raise
