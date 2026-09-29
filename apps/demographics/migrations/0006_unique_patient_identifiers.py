import uuid
from django.db import migrations, models

def assign_identifiers(apps, schema_editor):
    Patient = apps.get_model('demographics', 'Patient')
    HistoricalPatient = apps.get_model('demographics', 'HistoricalPatient')
    for patient in Patient.objects.all().iterator():
        key = uuid.uuid4()
        Patient.objects.filter(pk=patient.pk).update(medical_record_id=key)
        HistoricalPatient.objects.filter(id=patient.pk).update(medical_record_id=key)

class Migration(migrations.Migration):
    dependencies = [('demographics','0005_historicalpatient_allergy_status_and_more')]
    operations = [migrations.RunPython(assign_identifiers, migrations.RunPython.noop), migrations.AlterField(model_name='patient',name='medical_record_id',field=models.UUIDField(default=uuid.uuid4,editable=False,unique=True))]
