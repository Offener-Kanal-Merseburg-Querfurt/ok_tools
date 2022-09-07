# Generated by Django 4.0.5 on 2022-09-06 15:28

from django.db import migrations
from django.db import models
import contributions.models


class Migration(migrations.Migration):

    dependencies = [
        ('contributions', '0002_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DisaImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(
                    upload_to=contributions.models.DisaImport.timestamp_path, verbose_name='DISA export file')),
            ],
            options={
                'verbose_name': 'DISA-Import',
                'verbose_name_plural': 'DISA-Imports',
            },
        ),
    ]
