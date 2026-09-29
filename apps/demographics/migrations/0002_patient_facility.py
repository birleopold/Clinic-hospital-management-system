# Patient + historical patient facility FK; backfill when a single facility exists.

import django.db.models.deletion
from django.db import migrations, models


def backfill_patient_facility(apps, schema_editor):
    Facility = apps.get_model('accounts', 'Facility')
    Patient = apps.get_model('demographics', 'Patient')
    facilities = list(Facility.objects.all())
    if len(facilities) != 1:
        return
    fid = facilities[0].pk
    Patient.objects.filter(facility__isnull=True).update(facility_id=fid)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_department_facility_staffprofile_department_facility'),
        ('demographics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='facility',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='patients',
                to='accounts.facility',
            ),
        ),
        migrations.AddField(
            model_name='historicalpatient',
            name='facility',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+',
                to='accounts.facility',
            ),
        ),
        migrations.RunPython(backfill_patient_facility, noop_reverse),
    ]
