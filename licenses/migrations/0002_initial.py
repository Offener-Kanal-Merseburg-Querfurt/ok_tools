# Generated by Django 4.0.5 on 2022-10-05 08:45

from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('registration', '0001_initial'),
        ('licenses', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='license',
            name='profile',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    to='registration.profile', verbose_name='Profile'),
        ),
    ]
