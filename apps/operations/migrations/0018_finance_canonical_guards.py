import importlib
from django.db import migrations
original=importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')
NEW_MODELS={'operations.paymentrequest','operations.refundauthorization','operations.medicinereturn','operations.returnrefundlink','operations.priceoverride'}

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
    dependencies=[('operations','0017_historicalmedicinereturn_historicalpaymentrequest_and_more'),('inventory','0007_historicalpurchaseorder_approved_at_and_more')]
    operations=[migrations.RunPython(forward,backward)]
