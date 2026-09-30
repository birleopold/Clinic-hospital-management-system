from django.db import migrations


def seed(apps, schema_editor):
    Item=apps.get_model('inventory','InventoryItem')
    Profile=apps.get_model('pharmacy','MedicineProfile')
    # Preserve legacy inventory codes and every historical dispense. Do not infer
    # clinical classifications or pretend imported metadata has been reviewed.
    Profile.objects.using(schema_editor.connection.alias).bulk_create(
        [Profile(item_id=pk) for pk in Item.objects.using(schema_editor.connection.alias).values_list('pk',flat=True)],
        ignore_conflicts=True, batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies=[('pharmacy','0004_basketline_basketallocation_dispensingbasket_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
