# Generated by Django 4.0.5 on 2022-09-01 08:58

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0005_alter_project_media_education_supervisors'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='tn_diverse',
            field=models.IntegerField(default=0, verbose_name='diverse'),
        ),
    ]