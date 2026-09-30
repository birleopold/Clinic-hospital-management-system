import importlib
from django.db import migrations
original=importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')

def forward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    original.install(apps,schema_editor)

def backward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    class PreviousModels:
        def get_models(self):
            return [model for model in apps.get_models() if model._meta.label_lower!='operations.dutyassignment']
    original.install(PreviousModels(),schema_editor)

class Migration(migrations.Migration):
    dependencies=[('operations','0019_dutyshift_dutyassignment_attendance_and_more')]
    operations=[migrations.RunPython(forward,backward)]
