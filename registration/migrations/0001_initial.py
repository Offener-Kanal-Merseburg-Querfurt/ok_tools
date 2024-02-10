# Generated by Django 4.1.7 on 2024-02-10 11:01

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import registration.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='OKUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('email', models.EmailField(max_length=254, null=True, unique=True, verbose_name='email address')),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'User',
                'verbose_name_plural': 'Users',
            },
            managers=[
                ('objects', registration.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='MediaAuthority',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='OK Merseburg', max_length=150, unique=True, verbose_name='Media Authority')),
            ],
            options={
                'verbose_name': 'Media Authority',
                'verbose_name_plural': 'Media Authorities',
            },
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=150, null=True, verbose_name='first name')),
                ('last_name', models.CharField(max_length=150, null=True, verbose_name='last name')),
                ('gender', models.CharField(choices=[('none', 'not given'), ('m', 'male'), ('f', 'female'), ('d', 'diverse')], default='none', max_length=4, verbose_name='gender')),
                ('phone_number', models.CharField(blank=True, max_length=30, null=True, verbose_name='phone number')),
                ('mobile_number', models.CharField(blank=True, max_length=30, null=True, verbose_name='mobile number')),
                ('birthday', models.DateField(null=True, verbose_name='birthday')),
                ('street', models.CharField(max_length=95, null=True, verbose_name='street')),
                ('house_number', models.CharField(max_length=20, null=True, verbose_name='house number')),
                ('zipcode', models.CharField(max_length=5, null=True, verbose_name='zipcode')),
                ('city', models.CharField(max_length=35, null=True, verbose_name='city')),
                ('verified', models.BooleanField(default=False, help_text='The profile data was verified by showing the ID to an employee.', verbose_name='verified')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='created at')),
                ('member', models.BooleanField(default=False, verbose_name='member')),
                ('comment', models.TextField(blank=True, null=True, verbose_name='comment')),
                ('media_authority', models.ForeignKey(default=registration.models.default_media_authority, on_delete=django.db.models.deletion.CASCADE, to='registration.mediaauthority', verbose_name='Media Authority')),
                ('okuser', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='User')),
            ],
            options={
                'verbose_name': 'Profile',
                'verbose_name_plural': 'Profiles',
            },
        ),
    ]
