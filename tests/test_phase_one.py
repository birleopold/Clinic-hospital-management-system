import uuid
from datetime import timedelta
import pytest
from django.utils import timezone
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import CaptureQueriesContext
from django.db import connection
from apps.accounts.models import User, StaffProfile, Facility
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.orders.models import Order, OrderResult
from apps.appointments.models import QueueTicket
from apps.operations.models import WorkTask, NoteTemplate, ConsultationNote, PatientDocument, Specimen, ClinicalEntry
from tests.test_suite import suite

pytestmark=pytest.mark.django_db

def worker(s,role='lab'):
    u=User.objects.create_user(username='worker-'+role,role=role)
    StaffProfile.objects.update_or_create(user=u,defaults={'facility':s.f})
    return u

def test_task_assignment_revision_resolution_and_scope(suite):
    owner=worker(suite)
    data={'audience':'lab','owner':owner.pk,'title':'Review order','instruction':'Check the order queue','due_at':(timezone.now()+timedelta(hours=1)).isoformat()}
    response=suite.client.post(reverse('suite-task-create',args=[suite.p.pk]),data)
    assert response.status_code==302
    task=WorkTask.objects.get();assert task.facility==suite.f
    url=reverse('suite-task-detail',args=[task.pk])
    suite.client.force_login(owner)
    response=suite.client.post(url,{'revision':1,'owner':owner.pk,'status':'completed','resolution':''})
    assert response.status_code==200
    task.refresh_from_db();assert task.status=='open'
    response=suite.client.post(url,{'revision':1,'owner':owner.pk,'status':'in_progress','resolution':''})
    assert response.status_code==302
    response=suite.client.post(url,{'revision':1,'owner':owner.pk,'status':'completed','resolution':'Stale'})
    assert response.status_code==200
    task.refresh_from_db();assert task.status=='in_progress'
    suite.client.post(url,{'revision':2,'owner':owner.pk,'status':'completed','resolution':'Reviewed and released'})
    task.refresh_from_db();assert task.resolved_at and task.history.first().history_user==owner
    suite.client.post(url,{'revision':3,'owner':owner.pk,'status':'open','resolution':'Reopen'})
    task.refresh_from_db();assert task.status=='completed'
    outsider=worker(suite,'cashier');suite.client.force_login(outsider)
    assert suite.client.get(url).status_code==404

def test_general_task_and_cross_facility_owner(suite):
    other=worker(suite)
    f=Facility.objects.create(name='Other')
    StaffProfile.objects.filter(user=other).update(facility=f)
    data={'audience':'lab','owner':other.pk,'title':'Stock issue','due_at':timezone.now().isoformat()}
    response=suite.client.post('/suite/tasks/new/',data)
    assert response.status_code==200 and WorkTask.objects.count()==0
    data['owner']=''
    assert suite.client.post('/suite/tasks/new/',data).status_code==302
    assert WorkTask.objects.get().patient_id is None

def test_note_template_reuse_amendment_and_patient_checks(suite):
    visit=Encounter.objects.create(patient=suite.p,clinician=suite.u)
    template=NoteTemplate.objects.create(facility=suite.f,name='Consultation',version=1,body='Complaint:\nAssessment:\nPlan:',created_by=suite.u)
    url=reverse('suite-consultation-note',args=[visit.pk])
    assert suite.client.get(url,{'template':template.pk}).context['form'].initial['body']==template.body
    data={'template':template.pk,'body':'Reviewed synthetic note','reviewed':'on'}
    assert suite.client.post(url,data).status_code==302
    original=ConsultationNote.objects.get()
    assert original.template_snapshot==template.body
    data.update(copied_from=original.pk,amends=original.pk,body='Reviewed amendment')
    assert suite.client.post(url,data).status_code==302
    assert ConsultationNote.objects.latest('pk').copied_from==original
    original.refresh_from_db();assert original.body=='Reviewed synthetic note'
    visit.status='closed';visit.save()
    assert suite.client.post(url,data).status_code==200
    assert ConsultationNote.objects.count()==2
    other=Patient.objects.create(first_name='Other',last_name='Person',gender='M',facility=suite.f)
    other_visit=Encounter.objects.create(patient=other)
    assert suite.client.post(reverse('suite-consultation-note',args=[other_visit.pk]),data).status_code==200
    assert ConsultationNote.objects.count()==2

def test_private_document_validation_and_download(suite,settings,tmp_path):
    settings.MEDIA_ROOT=tmp_path
    url=reverse('suite-document-create',args=[suite.p.pk])
    response=suite.client.post(url,{'title':'Synthetic scan','file':SimpleUploadedFile('scan.pdf',b'%PDF-1.4\nsynthetic')})
    assert response.status_code==302
    doc=PatientDocument.objects.get()
    download=reverse('suite-document-download',args=[doc.pk])
    result=suite.client.get(download)
    assert result.status_code==200 and 'attachment' in result['Content-Disposition']
    assert 'no-store' in result['Cache-Control']
    # Consume Django test client's closing iterator so request cleanup preserves
    # the enclosing test transaction on PostgreSQL. Also verify the file bytes.
    assert b''.join(result.streaming_content)==b'%PDF-1.4\nsynthetic'
    assert suite.client.post(url,{'title':'Bad','file':SimpleUploadedFile('scan.pdf',b'<script>bad</script>')}).status_code==200
    assert PatientDocument.objects.count()==1
    suite.u.role='cashier';suite.u.save()
    assert suite.client.get(download).status_code==403

def test_scoped_lookup_and_contextual_form(suite):
    for n in range(40):Patient.objects.create(first_name=f'Lookup{n}',last_name='Synthetic',gender='M',facility=suite.f)
    p=Patient.objects.create(first_name='Needle',last_name='Person',gender='M',facility=suite.f)
    result=suite.client.get('/suite/lookup/clinical/patient/',{'q':'Needle'}).json()
    assert [r['id'] for r in result['results']]==[p.pk]
    assert suite.client.get('/suite/clinical/',{'patient':p.pk}).context['form'].initial['patient']==p.pk
    suite.u.role='cashier';suite.u.save()
    assert suite.client.get('/suite/lookup/clinical/patient/').status_code==403

def test_lab_board_stage_and_accession(suite):
    order=Order.objects.create(patient=suite.p,order_type='lab',code='SYNTHETIC')
    result=suite.client.get('/suite/department-board/',{'board':'lab','status':'collection'})
    assert result.context['page'].paginator.count==1
    specimen=Specimen.objects.create(order=order,status='received',specimen_type='Test',created_by=suite.u)
    result=suite.client.get('/suite/department-board/',{'board':'lab','status':'processing','scan':str(specimen.accession)})
    assert result.context['page'].paginator.count==1
    OrderResult.objects.create(order=order,result_text='Draft')
    result=suite.client.get('/suite/department-board/',{'board':'lab','status':'review'})
    assert result.context['page'].paginator.count==1
    suite.u.role='cashier';suite.u.save()
    assert suite.client.get('/suite/department-board/',{'board':'lab'}).status_code==403

def test_handoff_is_idempotent_and_does_not_complete_service(suite):
    url=reverse('suite-handoff',args=[suite.p.pk])
    for _ in range(2):assert suite.client.post(url,{'service':'triage'}).status_code==302
    assert QueueTicket.objects.filter(patient=suite.p,service='triage',status='waiting').count()==1
    suite.client.post(url,{'service':'consult'})
    assert QueueTicket.objects.filter(patient=suite.p).count()==2

def test_chart_large_history_has_bounded_page_queries(suite):
    for n in range(300):ClinicalEntry.objects.create(patient=suite.p,kind='note',text=f'History {n}',created_by=suite.u)
    with CaptureQueriesContext(connection) as queries:
        response=suite.client.get(reverse('suite-patient',args=[suite.p.pk]))
    assert response.status_code==200 and len(response.context['events'])==25
    assert len(queries)<65

def test_full_patient_journey_across_staff_roles(suite):
    from apps.billing.models import PriceList, PriceListItem, Invoice, CashSession, Payment
    from apps.pharmacy.models import Prescription, Dispense
    from rest_framework.test import APIClient
    staff={role:worker(suite,role) for role in ('reception','nurse','clinician','lab','pharmacy','cashier')}
    price=PriceList.objects.create(name='Synthetic prices')
    PriceListItem.objects.create(pricelist=price,code='LAB-FLOW',name='Synthetic lab',amount=100)
    PriceListItem.objects.create(pricelist=price,code='MED',name='Synthetic medicine',amount=10)
    c=suite.client;c.force_login(staff['reception'])
    response=c.post('/patients/new',{'first_name':'Journey','last_name':'Synthetic','gender':'F','phone':'+256700123456','consent_data_processing':'1'})
    assert response.status_code==302
    patient=Patient.objects.get(first_name='Journey')
    assert c.post(reverse('suite-handoff',args=[patient.pk]),{'service':'triage'}).status_code==302
    c.force_login(staff['nurse'])
    assert c.get('/ehr',{'patient':patient.pk}).context['context_patient']==patient
    assert c.post('/ehr/encounter/start',{'patient_id':patient.pk,'chief_complaint':'Synthetic workflow test'}).status_code==302
    visit=Encounter.objects.get(patient=patient)
    assert c.post(f'/ehr/encounter/{visit.pk}/vitals/add',{'temperature_c':'36.5','pulse':70}).status_code==302
    c.post(reverse('suite-handoff',args=[patient.pk]),{'service':'consult'})
    c.force_login(staff['clinician'])
    assert c.post(reverse('suite-claim-visit',args=[visit.pk])).status_code==302
    visit.refresh_from_db();assert visit.clinician==staff['clinician']
    assert c.post(reverse('suite-consultation-note',args=[visit.pk]),{'body':'Synthetic reviewed consultation','reviewed':'on'}).status_code==302
    assert c.post(f'/ehr/encounter/{visit.pk}/orders/create',{'code':'LAB-FLOW','order_type':'lab','quantity':1,'billable':'on'}).status_code==302
    order=Order.objects.get(patient=patient)
    c.post(reverse('suite-handoff',args=[patient.pk]),{'service':'lab'})
    c.force_login(staff['lab'])
    assert c.get('/suite/specimens/',{'order':order.pk}).context['form'].initial['order']==order.pk
    c.post('/suite/specimens/',{'order':order.pk,'specimen_type':'Synthetic'})
    specimen=Specimen.objects.get(order=order)
    c.post(f'/suite/specimens/{specimen.pk}/receive/')
    c.post('/suite/results/',{'order':order.pk,'specimen':specimen.pk,'result_text':'Synthetic result'})
    result=OrderResult.objects.get(order=order)
    c.force_login(staff['clinician'])
    c.post(f'/suite/results/{result.pk}/release/')
    result.refresh_from_db();assert result.approved_at is not None
    c.post(f'/ehr/encounter/{visit.pk}/rx/create')
    rx=Prescription.objects.get(patient=patient)
    c.post(f'/pharmacy/rx/{rx.pk}/items/add',{'item_code':'MED','item_name':'Medicine','quantity':1,'dose':'As recorded','frequency':'As recorded','duration':'As recorded'})
    assert rx.items.count()==1
    c.post(reverse('suite-handoff',args=[patient.pk]),{'service':'pharmacy'})
    c.force_login(staff['pharmacy'])
    assert all(p.patient_id==patient.pk for p in c.get('/pharmacy',{'patient':patient.pk}).context['prescriptions'])
    c.post('/pharmacy/dispense',{'patient_id':patient.pk,'prescription_item_id':rx.items.get().pk,'item_code':'MED','quantity':1,'batch_id':suite.b.pk})
    assert Dispense.objects.filter(patient=patient).count()==1
    c.post(reverse('suite-handoff',args=[patient.pk]),{'service':'cashier'})
    c.force_login(staff['cashier'])
    assert c.get('/cashier',{'patient':patient.pk}).status_code==200
    CashSession.objects.create(opened_by=staff['cashier'])
    api=APIClient();api.force_authenticate(staff['cashier'])
    for invoice in Invoice.objects.filter(patient=patient):
        if invoice.total_amount>0:
            response=api.post('/api/payments/',{'idempotency_key':str(uuid.uuid4()),'invoice':invoice.pk,'amount':str(invoice.total_amount),'method':'cash'})
            assert response.status_code==201,response.data
            invoice.refresh_from_db();assert invoice.paid_amount==invoice.total_amount
    assert Payment.objects.filter(invoice__patient=patient).exists()
    for service,role in [('triage','nurse'),('consult','clinician'),('lab','lab'),('pharmacy','pharmacy'),('cashier','cashier')]:
        api.force_authenticate(staff[role])
        ticket=QueueTicket.objects.get(patient=patient,service=service)
        assert api.post(f'/api/queue-tickets/{ticket.pk}/start/').status_code==200
        assert api.post(f'/api/queue-tickets/{ticket.pk}/finish/').status_code==200
    assert QueueTicket.objects.filter(patient=patient,status='done').count()==5
    assert ConsultationNote.objects.get(patient=patient).encounter==visit
    assert order.encounter==visit and rx.encounter==visit

def test_database_guards_cover_bulk_and_indirect_archived_writes(suite):
    from django.db import IntegrityError, transaction
    from apps.encounters.models import Vital
    visit=Encounter.objects.create(patient=suite.p)
    canonical=Patient.objects.create(first_name='Canonical',last_name='Identity',gender='F',facility=suite.f)
    suite.p.merged_into=canonical;suite.p.save()
    with pytest.raises(IntegrityError),transaction.atomic():
        ClinicalEntry.objects.bulk_create([ClinicalEntry(patient=suite.p,created_by=suite.u,kind='note',text='Must not save')])
    with pytest.raises(IntegrityError),transaction.atomic():
        Vital.objects.create(encounter=visit,pulse=70)


def test_visit_claim_preserves_owner_and_facility(suite):
    clinician=worker(suite,'clinician')
    nurse=worker(suite,'nurse')
    visit=Encounter.objects.create(patient=suite.p,clinician=nurse)
    url=reverse('suite-claim-visit',args=[visit.pk])
    suite.client.force_login(nurse)
    assert suite.client.post(url).status_code==403
    suite.client.force_login(clinician)
    assert suite.client.get(url).status_code==405
    assert suite.client.post(url).status_code==302
    visit.refresh_from_db();assert visit.clinician==clinician
    other=User.objects.create_user(username='second-clinician',role='clinician')
    StaffProfile.objects.update_or_create(user=other,defaults={'facility':suite.f})
    suite.client.force_login(other)
    assert suite.client.post(url).status_code==409
    visit.refresh_from_db();assert visit.clinician==clinician
    visit.status='closed';visit.save()
    suite.client.force_login(clinician)
    assert suite.client.post(url).status_code==409
    StaffProfile.objects.filter(user=clinician).update(facility=Facility.objects.create(name='Elsewhere'))
    assert suite.client.post(url).status_code==404
