import csv
import hashlib
import io
import json
from datetime import date
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.demographics.models import Patient
from .models import PatientImportBatch, PatientImportIdentity
from .extension_services import role, scoped_lock
from .workforce_services import facility_lock, reason_required

COLUMNS=['external_id','first_name','last_name','gender','date_of_birth','phone','email','address']


def fingerprint(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_row(facility,source,row):
    external=row['external_id']
    if not external or len(external)>100:raise ValidationError('External ID is required and limited to 100 characters.')
    values={key:value for key,value in row.items() if key!='external_id'}
    try:values['date_of_birth']=date.fromisoformat(values['date_of_birth']) if values['date_of_birth'] else None
    except ValueError:raise ValidationError('Date of birth must be YYYY-MM-DD or empty.')
    if values['date_of_birth'] and values['date_of_birth']>timezone.localdate():raise ValidationError('Date of birth cannot be in the future.')
    patient=Patient(facility=facility,**values)
    patient.full_clean(exclude=['created_at','updated_at'])
    existing=PatientImportIdentity.objects.filter(facility=facility,source=source,external_id=external).first()
    if existing:
        if existing.fingerprint!=fingerprint(row):raise ValidationError('Existing source identity has different data; reconcile manually. No overwrite is permitted.')
        return None
    matches=Patient.objects.filter(facility=facility,merged_into__isnull=True)
    if values['phone'] and matches.filter(phone=values['phone']).exists():raise ValidationError('Phone matches an existing patient; reconcile identity before importing.')
    if values['date_of_birth'] and matches.filter(first_name__iexact=values['first_name'],last_name__iexact=values['last_name'],date_of_birth=values['date_of_birth']).exists():raise ValidationError('Name and birth date match an existing patient; reconcile identity before importing.')
    return patient


@transaction.atomic
def preview(actor,facility,source,raw):
    role(actor,('admin','manager'));facility_lock(actor,facility.pk)
    if not source.strip() or len(source)>100:raise ValidationError('Name the source system (maximum 100 characters).')
    if len(raw)>1024*1024:raise ValidationError('Upload at most 1 MiB and 500 rows per reviewed batch.')
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if reader.fieldnames!=COLUMNS:raise ValidationError('Use the exact template column order.')
        rows=[];errors=[];seen=set()
        for index,item in enumerate(reader,2):
            if len(rows)>=500:raise ValidationError('Maximum 500 rows per reviewed batch.')
            if None in item or any(value is None for value in item.values()):raise ValidationError(f'Row {index}: incorrect column count.')
            row={key:value.strip() for key,value in item.items()};rows.append(row)
            try:
                if row['external_id'] in seen:raise ValidationError('Duplicate external ID within this batch.')
                seen.add(row['external_id']);validate_row(facility,source.strip(),row)
            except ValidationError as exc:errors.append({'row':index,'messages':exc.messages})
    except (UnicodeDecodeError,csv.Error):raise ValidationError('Upload a UTF-8 CSV using the provided template.')
    if not rows:raise ValidationError('The file contains no data rows.')
    return PatientImportBatch.objects.create(facility=facility,source=source.strip(),rows=rows,errors=errors,fingerprint=fingerprint(rows),created_by=actor)


@transaction.atomic
def commit(pk,actor,reason):
    role(actor,('admin','manager'))
    batch=scoped_lock(PatientImportBatch,pk,actor)
    facility_lock(actor,batch.facility_id)
    reason_required(reason)
    if batch.created_by_id==actor.pk:raise ValidationError('Another authorized reviewer must approve the import.')
    if batch.status=='committed':return batch
    if batch.status!='preview' or batch.errors or batch.fingerprint!=fingerprint(batch.rows):raise ValidationError('Only an unchanged error-free preview can be committed.')
    created=skipped=0
    for index,row in enumerate(batch.rows,2):
        try:patient=validate_row(batch.facility,batch.source,row)
        except ValidationError as exc:raise ValidationError(f'Row {index}: '+ '; '.join(exc.messages))
        if patient is None:skipped+=1;continue
        patient._history_user=actor;patient.save()
        PatientImportIdentity.objects.create(facility=batch.facility,source=batch.source,external_id=row['external_id'],patient=patient,fingerprint=fingerprint(row),batch=batch,created_by=actor)
        created+=1
    batch.created_count=created;batch.skipped_count=skipped;batch.status='committed';batch.reviewed_by=actor;batch.reviewed_at=timezone.now();batch.review_reason=reason;batch._history_user=actor;batch.save()
    return batch
