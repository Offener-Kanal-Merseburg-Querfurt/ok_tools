# Generated by Django 4.0.5 on 2022-09-21 09:13 - manually edited

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_alter_projectcategory_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='democracy_project',
            field=models.BooleanField(
                default=False, verbose_name='Democracy project'),
        ),
    ]