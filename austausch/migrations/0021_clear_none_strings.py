from django.db import migrations


def clear_none_strings(apps, schema_editor):
    """Replace the literal 'None' written for JSON null by ''."""
    ExchangeItem = apps.get_model('austausch', 'ExchangeItem')
    for field in ('bundesland', 'bundesland_code', 'title', 'description',
                  'sendeverantwortung'):
        ExchangeItem.objects.filter(**{field: 'None'}).update(**{field: ''})


class Migration(migrations.Migration):

    dependencies = [
        ('austausch', '0020_exchangeconfig_copy_chunk_size_mb_and_more'),
    ]

    operations = [
        migrations.RunPython(clear_none_strings, migrations.RunPython.noop),
    ]
