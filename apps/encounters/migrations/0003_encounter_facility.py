# Encounter facility FK + historical; backfill from patient / clinician.

import django.db.models.deletion
from django.db import migrations, models


def backfill_encounter_facility(apps, schema_editor):
    Encounter = apps.get_model('encounters', 'Encounter')
    StaffProfile = apps.get_model('accounts', 'StaffProfile')
    qs = (
        Encounter.objects.filter(facility__isnull=True)
        .select_related('patient')
        .iterator(chunk_size=500)
    )
    for enc in qs:
        fid = None
        patient = enc.patient
        if patient and patient.facility_id:
            fid = patient.facility_id
        if fid is None and enc.clinician_id:
            sp = StaffProfile.objects.filter(user_id=enc.clinician_id).first()
            if sp and sp.facility_id:
                fid = sp.facility_id
        if fid is not None:
            enc.facility_id = fid
            enc.save(update_fields=['facility'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_department_facility_staffprofile_department_facility'),
        ('demographics', '0002_patient_facility'),
        ('encounters', '0002_historicalvital_historicalencounter_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='facility',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='encounters',
                to='accounts.facility',
            ),
        ),
        migrations.AddField(
            model_name='historicalencounter',
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
        migrations.RunPython(backfill_encounter_facility, noop_reverse),
    ]
