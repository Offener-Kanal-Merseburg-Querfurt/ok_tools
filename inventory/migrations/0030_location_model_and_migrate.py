from django.db import migrations
from django.db import models
import django.db.models.deletion


def forwards(apps, schema_editor):
    InventoryItem = apps.get_model('inventory', 'InventoryItem')
    Location = apps.get_model('inventory', 'Location')

    names = set(
        InventoryItem.objects.exclude(location__isnull=True)
        .values_list('location', flat=True)
    )
    for name in names:
        if name:
            Location.objects.get_or_create(parent=None, name=name)

    for item in InventoryItem.objects.all():
        name = getattr(item, 'location', None)
        if not name:
            continue
        loc, _ = Location.objects.get_or_create(parent=None, name=name)
        setattr(item, 'location_new', loc)
        item.save(update_fields=['location_new'])


def backwards(apps, schema_editor):
    InventoryItem = apps.get_model('inventory', 'InventoryItem')
    for item in InventoryItem.objects.select_related('location').all():
        loc = getattr(item, 'location', None)
        setattr(item, 'location_old', loc.name if loc else None)
        item.save(update_fields=['location_old'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0029_remove_device_name_from_inspection'),
    ]

    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Name')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='inventory.location', verbose_name='Parent')),
            ],
            options={
                'verbose_name': 'Location',
                'verbose_name_plural': 'Locations',
                'unique_together': {('parent', 'name')},
                'ordering': ['parent__id', 'name'],
            },
        ),
        migrations.AddField(
            model_name='inventoryitem',
            name='location_new',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='inventory.location', verbose_name='Location'),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='inventoryitem',
            name='location',
        ),
        migrations.RenameField(
            model_name='inventoryitem',
            old_name='location_new',
            new_name='location',
        ),
        migrations.AlterField(
            model_name='inventoryitem',
            name='location',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inventory.location', verbose_name='Location'),
        ),
    ]
