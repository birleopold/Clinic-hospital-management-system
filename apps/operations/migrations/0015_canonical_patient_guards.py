"""Reject writes through archived identities at the database boundary.

PostgreSQL patient-row SHARE locks serialize canonical checks against merges.
SQLite serializes writers and uses BEFORE triggers for the same archive check.
Historical/provenance records intentionally retain old identities.
"""
from django.db import migrations

EXCLUDED={'demographics.patient','operations.patientmerge','operations.duplicatereview'}

def paths(model, seen=()):
    if model._meta.label_lower in seen or len(seen)>5:return []
    result=[]
    for field in model._meta.fields:
        if not field.is_relation or not field.many_to_one:continue
        related=field.related_model
        if not hasattr(related,'_meta') or related.__name__.startswith('Historical'):continue
        if related._meta.label_lower=='demographics.patient':result.append([field])
        elif related._meta.app_label not in ('accounts','auth','contenttypes'):
            result.extend([[field]+tail for tail in paths(related,seen+(model._meta.label_lower,))])
    return result

def install(apps,schema_editor):
    connection=schema_editor.connection
    if connection.vendor not in ('sqlite','postgresql'):return
    q=connection.ops.quote_name
    for model in apps.get_models():
        if model.__name__.startswith('Historical') or model._meta.label_lower in EXCLUDED:continue
        relations=paths(model)
        if not relations:continue
        table=model._meta.db_table;name=table+'_canonical_guard'
        checks=[]
        for path in relations:
            joins=[]
            for n,field in enumerate(path):
                target=field.related_model._meta.db_table
                if n==0:joins.append(f'FROM {q(target)} p0')
                else:joins.append(f'JOIN {q(target)} p{n} ON p{n}.{q(field.target_field.column)}=p{n-1}.{q(field.column)}')
            last=f'p{len(path)-1}'
            query=' '.join(joins)+f' WHERE p0.{q(path[0].target_field.column)}=NEW.{q(path[0].column)}'
            if connection.vendor=='postgresql':
                checks.append(f'SELECT {last}.merged_into_id INTO archived {query} FOR SHARE OF {last}; IF archived IS NOT NULL THEN RAISE EXCEPTION \'Patient identity was merged; reload its canonical record\' USING ERRCODE=\'23514\'; END IF;')
            else:
                checks.append(f"SELECT CASE WHEN EXISTS (SELECT 1 {query} AND {last}.merged_into_id IS NOT NULL) THEN RAISE(ABORT, 'Patient identity was merged; reload canonical record') END;")
        if connection.vendor=='postgresql':
            schema_editor.execute(f'CREATE OR REPLACE FUNCTION {q(name)}() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE archived bigint; BEGIN '+ ' '.join(checks)+' RETURN NEW; END $$')
            schema_editor.execute(f'CREATE TRIGGER {q(name)} BEFORE INSERT OR UPDATE ON {q(table)} FOR EACH ROW EXECUTE FUNCTION {q(name)}()')
        else:
            for action in ('INSERT','UPDATE'):
                schema_editor.execute(f'CREATE TRIGGER {q(name+"_"+action.lower())} BEFORE {action} ON {q(table)} BEGIN '+ ' '.join(checks)+' END')

def uninstall(apps,schema_editor):
    connection=schema_editor.connection;q=connection.ops.quote_name
    for model in apps.get_models():
        table=model._meta.db_table;name=table+'_canonical_guard'
        if model.__name__.startswith('Historical') or model._meta.label_lower in EXCLUDED or not paths(model):continue
        if connection.vendor=='postgresql':
            schema_editor.execute(f'DROP TRIGGER IF EXISTS {q(name)} ON {q(table)}')
            schema_editor.execute(f'DROP FUNCTION IF EXISTS {q(name)}()')
        elif connection.vendor=='sqlite':
            for action in ('insert','update'):schema_editor.execute(f'DROP TRIGGER IF EXISTS {q(name+"_"+action)}')

class Migration(migrations.Migration):
    dependencies=[('operations', '0014_historicalworktask_facility_and_more'), ('appointments', '0004_appointment_room'), ('billing', '0004_alter_historicalpayment_method_alter_payment_method'), ('orders', '0006_historicalorderresult_catalog_analyte_and_more'), ('pharmacy', '0003_dispense_batch_historicaldispense_batch_and_more'), ('inventory', '0006_historicalpurchaseorder_facility_and_more')]
    operations=[migrations.RunPython(install,uninstall)]
