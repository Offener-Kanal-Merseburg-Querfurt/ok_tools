# Generated by Django 4.0.5 on 2022-07-19 08:32

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='profile',
            options={'permissions': [
                ('verified', 'Can access functionalities for verified users')]},
        ),
    ]
