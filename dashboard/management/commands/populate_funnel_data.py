from contributions.models import Contribution
from dashboard.models import FunnelMetrics
from dashboard.models import UserJourney
from dashboard.models import UserJourneyStage
from dashboard.utils import FunnelTracker
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from licenses.models import Category
from licenses.models import License
from registration.models import MediaAuthority
from registration.models import OKUser
from registration.models import Profile
from rental.models import RentalRequest
import random


class Command(BaseCommand):
    help = 'Populate funnel data for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--users',
            type=int,
            default=100,
            help='Number of test users to create'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to generate data for'
        )

    def handle(self, *args, **options):
        users_count = options['users']
        days = options['days']

        self.stdout.write(f"Creating {users_count} test users over {days} days...")

        try:
            # Get or create default media authority
            media_authority, _ = MediaAuthority.objects.get_or_create(
                name='Test Authority'
            )

            # Get or create default category
            category, _ = Category.objects.get_or_create(
                name='Test Category',
                defaults={'name': 'Test Category'}
            )

            # Create test users
            users = []
            for i in range(users_count):
                email = f"test_user_{i}@example.com"
                user, created = OKUser.objects.get_or_create(
                    email=email,
                    defaults={'is_active': True}
                )

                if created:
                    # Create profile
                    profile, _ = Profile.objects.get_or_create(
                        okuser=user,
                        defaults={
                            'first_name': f'Test{i}',
                            'last_name': 'User',
                            'gender': random.choice(['M', 'F', 'NOT']),
                            'birthday': timezone.now().date() - timedelta(days=random.randint(18, 65) * 365),
                            'street': 'Test Street',
                            'house_number': str(i),
                            'zipcode': '12345',
                            'city': 'Test City',
                            'verified': random.choice([True, False]),
                            'media_authority': media_authority,
                            'member': random.choice([True, False])
                        }
                    )

                    # Randomly set verification date
                    if profile.verified:
                        profile.created_at = timezone.now() - timedelta(days=random.randint(1, days))
                        profile.save()

                    users.append(user)

            self.stdout.write(f"Created {len(users)} users")

            # Generate activities over time
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days)

            current_date = start_date
            while current_date <= end_date:
                # Randomly select users for activities on this date
                daily_users = random.sample(users, random.randint(1, min(10, len(users))))

                for user in daily_users:
                    # Random activities based on user's current stage
                    user_journey = UserJourney.objects.filter(user=user).order_by('achieved_at')
                    current_stages = [j.stage for j in user_journey]

                    # Registration (if not already registered)
                    if UserJourneyStage.REGISTERED not in current_stages:
                        if random.random() < 0.1:  # 10% chance per day
                            UserJourney.objects.create(
                                user=user,
                                stage=UserJourneyStage.REGISTERED,
                                achieved_at=timezone.make_aware(
                                    timezone.datetime.combine(current_date, timezone.datetime.min.time())
                                ) + timedelta(hours=random.randint(0, 23))
                            )

                    # Verification (if registered but not verified)
                    elif UserJourneyStage.VERIFIED not in current_stages:
                        if random.random() < 0.2:  # 20% chance per day
                            UserJourney.objects.create(
                                user=user,
                                stage=UserJourneyStage.VERIFIED,
                                achieved_at=timezone.make_aware(
                                    timezone.datetime.combine(current_date, timezone.datetime.min.time())
                                ) + timedelta(hours=random.randint(0, 23))
                            )

                    # Rental request (if verified but no rental)
                    elif UserJourneyStage.RENTAL_REQUESTED not in current_stages:
                        if random.random() < 0.05:  # 5% chance per day
                            rental = RentalRequest.objects.create(
                                user=user,
                                created_by=user,
                                project_name=f"Test Project {user.id}",
                                purpose="Test purpose",
                                requested_start_date=timezone.now() + timedelta(days=1),
                                requested_end_date=timezone.now() + timedelta(days=7),
                                status='draft'
                            )
                            UserJourney.objects.create(
                                user=user,
                                stage=UserJourneyStage.RENTAL_REQUESTED,
                                rental_request=rental,
                                achieved_at=timezone.make_aware(
                                    timezone.datetime.combine(current_date, timezone.datetime.min.time())
                                ) + timedelta(hours=random.randint(0, 23))
                            )

                    # License creation (if verified but no license)
                    elif UserJourneyStage.LICENSE_CREATED not in current_stages:
                        if random.random() < 0.1:  # 10% chance per day
                            # Get user's profile
                            user_profile = Profile.objects.filter(okuser=user).first()
                            if user_profile:
                                license = License.objects.create(
                                    title=f"Test License {user.id}",
                                    description="Test license description",
                                    profile=user_profile,
                                    category=category,
                                    duration=timedelta(minutes=random.randint(5, 120))
                                )
                                UserJourney.objects.create(
                                    user=user,
                                    stage=UserJourneyStage.LICENSE_CREATED,
                                    license=license,
                                    achieved_at=timezone.make_aware(
                                        timezone.datetime.combine(current_date, timezone.datetime.min.time())
                                    ) + timedelta(hours=random.randint(0, 23))
                                )

                    # Contribution creation (if has license but no contribution)
                    elif UserJourneyStage.CONTRIBUTION_CREATED not in current_stages:
                        if random.random() < 0.15:  # 15% chance per day
                            # Get user's latest license
                            user_profile = Profile.objects.filter(okuser=user).first()
                            if user_profile:
                                user_license = License.objects.filter(profile=user_profile).order_by('-created_at').first()
                                if user_license:
                                    contribution = Contribution.objects.create(
                                        license=user_license,
                                        broadcast_date=timezone.make_aware(
                                            timezone.datetime.combine(current_date, timezone.datetime.min.time())
                                        ) + timedelta(hours=random.randint(0, 23)),
                                        live=random.choice([True, False])
                                    )
                                    UserJourney.objects.create(
                                        user=user,
                                        stage=UserJourneyStage.CONTRIBUTION_CREATED,
                                        contribution=contribution,
                                        achieved_at=contribution.broadcast_date
                                    )

                current_date += timedelta(days=1)

            # Generate funnel metrics for each day
            tracker = FunnelTracker()
            current_date = start_date
            while current_date <= end_date:
                tracker.cache_funnel_metrics(current_date)
                current_date += timedelta(days=1)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully populated funnel data for {len(users)} users over {days} days"
                )
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error populating funnel data: {e}")
            )
            raise
