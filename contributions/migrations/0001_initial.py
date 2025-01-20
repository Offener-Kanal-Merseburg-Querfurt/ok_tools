# Generated by Django 4.1.7 on 2024-02-10 11:01

from django.db import migrations
from django.db import models
import contributions.models
import django.core.validators


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Contribution',
            fields=[
                ('id', models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name='ID')),
                ('broadcast_date', models.DateTimeField(
                    verbose_name='Broadcast Date')),
                ('live', models.BooleanField(verbose_name='Is live')),
            ],
            options={
                'verbose_name': 'Contribution',
                'verbose_name_plural': 'Contributions',
            },
        ),
        migrations.CreateModel(
            name='DisaImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to=contributions.models.DisaImport.timestamp_path, validators=[
                 django.core.validators.FileExtensionValidator(allowed_extensions=['xlsx'])], verbose_name='DISA export file')),
                ('imported', models.BooleanField(default=False,
                 help_text='Just marking the file as imported does not import the file!', verbose_name='Imported')),
            ],
            options={
                'verbose_name': 'DISA-Import',
                'verbose_name_plural': 'DISA-Imports',
            },
        ),
    ]
