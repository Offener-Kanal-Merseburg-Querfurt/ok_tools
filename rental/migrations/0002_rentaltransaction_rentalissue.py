from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rental', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RentalTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('reserve', 'Reserve'), ('issue', 'Issue'), ('return', 'Return'), ('cancel', 'Cancel')], max_length=20, verbose_name='Transaction type')),
                ('quantity', models.PositiveIntegerField(verbose_name='Quantity')),
                ('performed_at', models.DateTimeField(auto_now_add=True, verbose_name='Performed at')),
                ('condition', models.CharField(blank=True, choices=[('excellent', 'Excellent'), ('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor')], max_length=20, verbose_name='Condition')),
                ('notes', models.TextField(blank=True, verbose_name='Notes')),
                ('performed_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='Performed by')),
                ('rental_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='rental.rentalitem', verbose_name='Rental item')),
            ],
            options={
                'verbose_name': 'Rental transaction',
                'verbose_name_plural': 'Rental transactions',
                'ordering': ['-performed_at'],
            },
        ),
        migrations.CreateModel(
            name='RentalIssue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('issue_type', models.CharField(choices=[('damaged', 'Damaged'), ('missing', 'Missing'), ('late_return', 'Late Return'), ('other', 'Other')], max_length=20, verbose_name='Issue type')),
                ('description', models.TextField(verbose_name='Description')),
                ('severity', models.CharField(choices=[('minor', 'Minor'), ('major', 'Major'), ('critical', 'Critical')], max_length=20, verbose_name='Severity')),
                ('reported_at', models.DateTimeField(auto_now_add=True, verbose_name='Reported at')),
                ('resolved', models.BooleanField(default=False, verbose_name='Resolved')),
                ('resolution_notes', models.TextField(blank=True, verbose_name='Resolution notes')),
                ('reported_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='Reported by')),
                ('rental_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='issues', to='rental.rentalitem', verbose_name='Rental item')),
            ],
            options={
                'verbose_name': 'Rental issue',
                'verbose_name_plural': 'Rental issues',
                'ordering': ['-reported_at'],
            },
        ),
    ]
