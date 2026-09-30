import importlib
from django.db import migrations
original=importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')
NEW_MODELS={'operations.appointmentrequest','operations.portalrecipient','operations.patientrecall'}

def forward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    original.install(apps,schema_editor)

def backward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    class PreviousModels:
        def get_models(self):return [m for m in apps.get_models() if m._meta.label_lower not in NEW_MODELS]
    original.install(PreviousModels(),schema_editor)

class Migration(migrations.Migration):
    dependencies=[('operations','0026_appointmentrequest_historicalappointmentrequest_and_more')]
    operations=[migrations.RunPython(forward,backward)]
