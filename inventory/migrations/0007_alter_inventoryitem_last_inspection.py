# Generated by Django 4.1.7 on 2025-05-04 21:47

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_alter_inventoryitem_last_inspection'),
    ]

    operations = [
        migrations.AlterField(
            model_name='inventoryitem',
            name='last_inspection',
            field=models.CharField(blank=True, help_text="Enter the number in the format XXXXXX or select 'no inspection'", max_length=20, null=True, verbose_name='E-Inspection'),
        ),
    ]
