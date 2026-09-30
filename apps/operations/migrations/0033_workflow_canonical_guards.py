import importlib
from django.db import migrations
original=importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')


def refresh(apps,schema_editor):
    original.uninstall(apps,schema_editor)
    original.install(apps,schema_editor)


def backward(apps,schema_editor):
    from django.db.migrations.loader import MigrationLoader
    original.uninstall(apps,schema_editor)
    previous=MigrationLoader(schema_editor.connection).project_state([('operations','0031_import_canonical_guards')])
    original.install(previous.apps,schema_editor)


class Migration(migrations.Migration):
    dependencies=[('operations','0032_appointmentrequest_kind_and_more'),('accounts','0009_facilityconfiguration_logo_and_more')]
    operations=[migrations.RunPython(refresh,backward)]
