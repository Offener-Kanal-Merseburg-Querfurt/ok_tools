# Generated by Django 4.1.7 on 2025-01-14 20:37

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('licenses', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='license',
            name='youth_protection_category',
            field=models.CharField(
                choices=[
                    ('none', 'not necessary'),
                    ('from_12', 'from 12'),
                    ('from_16', 'from 16'),
                    ('from_18', 'from 18')],
                default='none',
                null=True,
                max_length=255,
                verbose_name='Youth protection category'),
        ),
        migrations.AddField(
            model_name='license',
            name='media_authority_exchange_allowed_other_states',
            field=models.BooleanField(null=True, verbose_name='Media Authority exchange allowed in other states than Saxony-Anhalt.'),
        ),
        migrations.AlterField(
            model_name='license',
            name='media_authority_exchange_allowed',
            field=models.BooleanField(null=True, verbose_name='Media Authority exchange allowed in Saxony-Anhalt'),
        ),
    ]
