import csv
import io
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
import pytest
from apps.demographics.models import Patient
from apps.operations.import_services import preview,commit,COLUMNS
from apps.operations.models import PatientImportIdentity
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


def data(*rows):
    out=io.StringIO();writer=csv.writer(out);writer.writerow(COLUMNS);writer.writerows(rows);return out.getvalue().encode()


def test_preview_independent_commit_replay_and_no_inferred_consent(team,client):
    t=team;raw=data(['X1','Synthetic','Imported','F','1990-01-01','+256700000001','',''])
    batch=preview(t.manager,t.f,'Legacy clinic',raw)
    assert not batch.errors and not Patient.objects.exists()
    with pytest.raises(ValidationError,match='Another'):commit(batch.pk,t.manager,'Self')
    with pytest.raises(PermissionDenied):commit(batch.pk,t.outsider,'Other facility')
    batch=commit(batch.pk,t.manager2,'Checked source register and row counts')
    assert batch.created_count==1 and Patient.objects.count()==1
    patient=Patient.objects.get();assert not patient.consent_data_processing and patient.allergy_status=='unknown'
    assert commit(batch.pk,t.manager2,'Retry').created_count==1
    second=preview(t.manager,t.f,'Legacy clinic',raw);second=commit(second.pk,t.manager2,'Reconcile duplicate upload')
    assert second.skipped_count==1 and second.created_count==0 and PatientImportIdentity.objects.count()==1
    client.force_login(t.manager)
    for path in ['/suite/setup/','/suite/imports/',f'/suite/imports/{batch.pk}/']:
        assert client.get(path).status_code==200
    assert client.get('/suite/imports/?download=template')['Content-Type']=='text/csv'


def test_errors_identity_conflicts_and_atomic_revalidation(team):
    t=team
    batch=preview(t.manager,t.f,'Legacy',data(['X1','First','Import','F','invalid','','','']))
    assert batch.errors
    with pytest.raises(ValidationError):commit(batch.pk,t.manager2,'Try')
    raw=data(['X1','First','Import','F','1990-01-01','+256700000001','',''],['X2','Second','Import','M','1980-01-01','+256700000002','',''])
    batch=preview(t.manager,t.f,'Legacy',raw)
    Patient.objects.create(first_name='Registered',last_name='Since preview',gender='M',phone='+256700000002',facility=t.f)
    with pytest.raises(ValidationError,match='Row 3'):commit(batch.pk,t.manager2,'Checked')
    assert Patient.objects.count()==1 and not PatientImportIdentity.objects.exists()
    duplicate=preview(t.manager,t.f,'Legacy',data(['X1','First','Import','F','','','',''],['X1','Second','Import','M','','','','']))
    assert duplicate.errors
