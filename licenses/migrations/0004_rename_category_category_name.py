# Generated by Django 4.0.5 on 2022-08-03 12:03

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('licenses', '0003_licensetemplate_licenserequest_delete_license'),
    ]

    operations = [
        migrations.RenameField(
            model_name='category',
            old_name='category',
            new_name='name',
        ),
    ]
