from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rental.models import RentalRequest
from rental.models import RentalTransaction
from rental.models import RoomRental
import logging


logger = logging.getLogger(__name__)
OKUser = get_user_model()


class Command(BaseCommand):
    """Management command to expire room rentals and generate transactions."""

    help = 'Automatically expire room rentals and create corresponding transactions.'

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without applying changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Verbose output',
        )

    def handle(self, *args, **options):
        """Execute command logic to expire reservations and rentals."""
        dry_run = options['dry_run']
        verbose = options['verbose']

        self.stdout.write(
            self.style.SUCCESS('🚀 Starting automatic expiration of expired room rentals...')
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('⚠️  TEST MODE - changes will not be applied')
            )

        # Find all active room rentals that have expired
        now = timezone.now()
        expired_rentals = []

        # Get all active room rentals
        active_room_rentals = RoomRental.objects.filter(
            rental_request__status__in=['reserved', 'issued']
        ).select_related('rental_request', 'room')

        for room_rental in active_room_rentals:
            if room_rental.is_expired:
                expired_rentals.append(room_rental)

        if not expired_rentals:
            self.stdout.write(
                self.style.SUCCESS('✅ No expired room rentals found')
            )
            return

        self.stdout.write(
            f'📊 Found {len(expired_rentals)} expired room rentals'
        )

        # Group by status for better display
        reserved_expired = [r for r in expired_rentals if r.rental_request.status == 'reserved']
        issued_expired = [r for r in expired_rentals if r.rental_request.status == 'issued']

        if reserved_expired:
            self.stdout.write(
                f'🔴 {len(reserved_expired)} expired room reservations'
            )

        if issued_expired:
            self.stdout.write(
                f'🟡 {len(issued_expired)} expired room rentals'
            )

        if verbose:
            self.stdout.write('\n📋 Details of expired rentals:')
            for rental in expired_rentals:
                status = 'RESERVED' if rental.rental_request.status == 'reserved' else 'ISSUED'
                self.stdout.write(
                    f'  • {rental.room.name} - {rental.rental_request.project_name} '
                    f'({status}) - Expired: {rental.rental_request.requested_end_date.strftime("%d.%m.%Y %H:%M")}'
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('\n⚠️  In test mode, changes are not applied')
            )
            return

        # Apply changes
        self.stdout.write('\n🔄 Applying changes...')

        try:
            with transaction.atomic():
                processed_count = 0

                for room_rental in expired_rentals:
                    rental_request = room_rental.rental_request

                    if rental_request.status == 'reserved':
                        # For reservations: create cancellation transaction
                        RentalTransaction.objects.create(
                            room=room_rental.room,
                            transaction_type='cancel',
                            quantity=1,  # Room = 1 unit
                            notes=_('Automatic cancellation of expired room reservation: {}').format(room_rental.room.name),
                            performed_by=OKUser.objects.filter(is_superuser=True).first()
                        )

                        # Update request status
                        rental_request.status = 'cancelled'
                        rental_request.save()

                        if verbose:
                            self.stdout.write(
                                f'  ✅ Cancelled reservation: {room_rental.room.name}'
                            )

                    elif rental_request.status == 'issued':
                        # For rentals: create return transaction
                        RentalTransaction.objects.create(
                            room=room_rental.room,
                            transaction_type='return',
                            quantity=1,  # Room = 1 unit
                            notes=_('Automatic return of expired room rental: {}').format(room_rental.room.name),
                            performed_by=OKUser.objects.filter(is_superuser=True).first()
                        )

                        # Update request status and return date
                        rental_request.status = 'returned'
                        rental_request.actual_end_date = now
                        rental_request.save()

                        if verbose:
                            self.stdout.write(
                                f'  ✅ Returned room: {room_rental.room.name}'
                            )

                    processed_count += 1

                self.stdout.write(
                    self.style.SUCCESS(f'\n✅ Successfully processed {processed_count} expired room rentals')
                )

                # Log result
                logger.info(
                    _('Automatic expiration of expired room rentals: '
                      'processed {} rentals, '
                      'reservations: {}, '
                      'rentals: {}').format(
                        processed_count,
                        len(reserved_expired),
                        len(issued_expired)
                    )
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n❌ Error during processing: {str(e)}')
            )
            logger.error(_('Error during automatic expiration of expired room rentals: {}').format(str(e)))
            raise

        self.stdout.write(
            self.style.SUCCESS('\n🎉 Automatic expiration of expired room rentals completed!')
        )
