# Generated by Django 4.0.5 on 2022-08-29 14:15

from django.db import migrations
from django.db import models
from django.utils.timezone import utc
import datetime


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0003_alter_profile_created_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='created_at',
            field=models.DateTimeField(default=datetime.datetime(
                2022, 8, 29, 14, 15, 37, 780571, tzinfo=utc)),
        ),
    ]
