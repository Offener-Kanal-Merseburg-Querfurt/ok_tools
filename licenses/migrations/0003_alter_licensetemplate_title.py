# Generated by Django 4.0.5 on 2022-08-31 14:08

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('licenses', '0002_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='licensetemplate',
            name='title',
            field=models.CharField(
                max_length=255, null=True, verbose_name='Title'),
        ),
    ]
