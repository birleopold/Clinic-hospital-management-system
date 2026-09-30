"""Refresh identity guards for new basket/line/allocation paths."""
import importlib
from django.db import migrations

original=importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')
NEW_MODELS={'pharmacy.dispensingbasket','pharmacy.basketline','pharmacy.basketallocation'}


def forward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    original.install(apps,schema_editor)


def backward(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    class PreviousModels:
        def get_models(self):
            return [model for model in apps.get_models() if model._meta.label_lower not in NEW_MODELS]
    original.install(PreviousModels(),schema_editor)


class Migration(migrations.Migration):
    dependencies=[('operations','0015_canonical_patient_guards'),('pharmacy','0005_seed_medicine_profiles')]
    operations=[migrations.RunPython(forward,backward)]
