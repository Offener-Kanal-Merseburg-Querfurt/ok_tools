# Generated by Django 4.0.5 on 2022-08-25 09:32

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contributions', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='contribution',
            old_name='broadcast_dae',
            new_name='broadcast_date',
        ),
    ]