# Generated by Django 4.1.7 on 2025-04-28 21:12

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='TagesPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('datum', models.DateField(unique=True)),
                ('json_plan', models.JSONField(blank=True, default=dict)),
                ('kommentar', models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='CalendarWeeksProxy',
            fields=[
            ],
            options={
                'verbose_name': 'Calendar weeks',
                'verbose_name_plural': 'Calendar weeks',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('planung.tagesplan',),
        ),
    ]
