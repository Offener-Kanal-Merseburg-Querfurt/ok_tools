# Generated by Django 4.0.5 on 2022-07-13 13:14

from django.db import migrations
from django.db import models
import datetime


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='birthday',
            field=models.DateField(default=datetime.date(
                1990, 9, 1), verbose_name='birthday'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='city',
            field=models.CharField(
                default='Merseburg', max_length=35, null=True, verbose_name='city'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='first_name',
            field=models.CharField(
                max_length=150, null=True, verbose_name='first name'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='gender',
            field=models.CharField(choices=[('none', 'Not Given'), ('m', 'Male'), ('f', 'Female'), (
                'd', 'Diverse')], default='none', max_length=4, verbose_name='gender'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='house_number',
            field=models.CharField(
                max_length=20, null=True, verbose_name='house_number'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='last_name',
            field=models.CharField(
                max_length=150, null=True, verbose_name='last_name'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='mobile_number',
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name='mobile number'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='phone_number',
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name='phone number'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='street',
            field=models.CharField(
                max_length=95, null=True, verbose_name='street'),
        ),
        migrations.AlterField(
            model_name='profile',
            name='zipcode',
            field=models.CharField(
                default='06217', max_length=5, null=True, verbose_name='zipcode'),
        ),
    ]
