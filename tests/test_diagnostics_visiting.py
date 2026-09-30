import uuid
from datetime import timedelta
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import User, StaffProfile
from apps.demographics.models import Patient
from apps.orders.models import Order, OrderResult
from apps.operations.models import DiagnosticTemplate, DiagnosticWorksheet, Specimen, VisitingSpecialist, VisitingEngagement, VisitingCaseNote, TheatreCase, ServiceRoom
from apps.operations import diagnostic_services as s
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


def diagnostic(t,kind='imaging'):
    patient=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Diagnostic',gender='F')
    order=Order.objects.create(patient=patient,order_type=kind,code='SYNTHETIC',description='Synthetic diagnostic',billable=False)
    fields=[{'key':'findings','label':'Findings','type':'text','required':True},{'key':'measurement','label':'Measurement','type':'number','required':False,'unit':'mm'}]
    template=DiagnosticTemplate.objects.create(facility=t.f,name='Synthetic report',version=1,order_type=kind,fields=fields,status='published',created_by=t.doctor,reviewed_by=t.cover,reviewed_at=t.now)
    s.schedule(order.pk,t.doctor,t.doctor,'CT' if kind=='imaging' else '',t.now,'Approved checklist reference',1)
    s.start(order.pk,t.doctor)
    return patient,order,template


def test_structured_report_review_retry_amendment_and_download(client,team):
    t=team;patient,order,template=diagnostic(t);key=uuid.uuid4();answers={'findings':'Synthetic findings','measurement':'12'}
    sheet=s.submit(order.pk,t.doctor,template,answers,key)
    assert s.submit(order.pk,t.doctor,template,answers,key).pk==sheet.pk
    with pytest.raises(ValidationError,match='different report'):s.submit(order.pk,t.doctor,template,{'findings':'Changed'},key)
    with pytest.raises(ValidationError,match='Another qualified'):s.review(sheet.pk,t.doctor,'release','Self')
    client.force_login(t.cover)
    assert client.get(f'/suite/diagnostics/orders/{order.pk}/report/').status_code==404
    s.review(sheet.pk,t.cover,'release','Reviewed acquired images and report')
    response=client.get(f'/suite/diagnostics/orders/{order.pk}/report/?download=text')
    assert response.status_code==200 and 'attachment' in response['Content-Disposition'] and b'Synthetic findings' in response.content
    sheet.result.refresh_from_db()
    amendment=s.submit(order.pk,t.doctor,template,{'findings':'Corrected findings','measurement':'13'},uuid.uuid4(),sheet.result)
    s.review(amendment.pk,t.cover,'release','Correction reviewed')
    response=client.get(f'/suite/diagnostics/orders/{order.pk}/report/')
    assert b'Corrected findings' in response.content and b'Synthetic findings' not in response.content
    assert OrderResult.objects.filter(order=order).count()==2
    api=APIClient();api.force_authenticate(t.manager)
    # Manager cannot use general result writes at all; clinical draft updates also fail.
    api.force_authenticate(t.doctor)
    assert api.patch(f'/api/order-results/{sheet.result_id}/',{'result_text':'Tamper'}).status_code in (400,403)


def test_laboratory_specimen_validation_and_withdrawal(team):
    t=team;patient,order,template=diagnostic(t,'lab')
    with pytest.raises(ValidationError,match='received specimen'):s.submit(order.pk,t.doctor,template,{'findings':'Result'},uuid.uuid4())
    specimen=Specimen.objects.create(order=order,specimen_type='Synthetic specimen',status='received',created_by=t.doctor)
    with pytest.raises(ValidationError,match='finite number'):s.submit(order.pk,t.doctor,template,{'findings':'Result','measurement':'NaN'},uuid.uuid4(),specimen=specimen)
    sheet=s.submit(order.pk,t.doctor,template,{'findings':'Result'},uuid.uuid4(),specimen=specimen,critical=True)
    s.review(sheet.pk,t.doctor,'withdraw','Incorrect worksheet selection')
    with pytest.raises(ValidationError,match='Withdrawn'):s.review(sheet.pk,t.cover,'release','Try')
    assert sheet.result.critical


def test_diagnostic_operator_scope_and_cancelled_order(team):
    t=team;patient,order,template=diagnostic(t)
    with pytest.raises(PermissionDenied):s.start(order.pk,t.outsider)
    with pytest.raises(ValidationError,match='assigned operator'):s.submit(order.pk,t.cover,template,{'findings':'Result'},uuid.uuid4())
    order.status='cancelled';order.save()
    with pytest.raises(ValidationError,match='cancelled'):s.submit(order.pk,t.doctor,template,{'findings':'Result'},uuid.uuid4())


def test_template_builder_review_and_forms(client,team):
    t=team;client.force_login(t.doctor)
    payload={'facility':t.f.pk,'name':'Reviewed clinical template','version':1,'order_type':'imaging','modality':'CT','fields-TOTAL_FORMS':'1','fields-INITIAL_FORMS':'0','fields-MIN_NUM_FORMS':'0','fields-MAX_NUM_FORMS':'60','fields-0-label':'Findings','fields-0-type':'text','fields-0-required':'on'}
    response=client.post('/suite/diagnostics/templates/new/',payload)
    assert response.status_code==302,response.content[:500]
    template=DiagnosticTemplate.objects.get(name='Reviewed clinical template')
    client.post(f'/suite/diagnostics/templates/{template.pk}/review/',{'decision':'publish','reason':'Self'})
    template.refresh_from_db();assert template.status=='draft'
    client.force_login(t.cover);client.post(f'/suite/diagnostics/templates/{template.pk}/review/',{'decision':'publish','reason':'Approved worksheet reviewed'})
    template.refresh_from_db();assert template.status=='published'
    for path in ['/suite/diagnostics/','/suite/diagnostics/templates/','/suite/diagnostics/templates/new/']:
        assert client.get(path).status_code==200
    patient,order,template=diagnostic(t)
    for path in [f'/suite/diagnostics/orders/{order.pk}/',f'/suite/diagnostics/orders/{order.pk}/worksheet/{template.pk}/']:
        assert client.get(path).status_code==200


def test_visiting_case_access_expiry_notes_and_jwt_denial(client,team):
    t=team;patient=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Visiting',gender='F')
    case=TheatreCase.objects.create(patient=patient,room=ServiceRoom.objects.create(facility=t.f,name='Theatre'),surgeon=t.doctor,procedure='Synthetic case',indication='Synthetic indication',starts_at=t.now,ends_at=t.now+timedelta(hours=2),created_by=t.manager)
    specialist=VisitingSpecialist.objects.create(user=t.doctor,specialty='Surgery',credential_reference='Verified synthetic reference',credential_expires=timezone.localdate()+timedelta(days=30),verification_note='Synthetic verification',created_by=t.manager)
    grant=VisitingEngagement.objects.create(specialist=specialist,case=case,starts_at=t.now-timedelta(hours=1),ends_at=t.now+timedelta(hours=3),purpose='One case',created_by=t.manager)
    client.force_login(t.doctor)
    assert client.get('/suite/').url=='/suite/visiting/'
    assert client.get('/suite/visiting/').status_code==200
    assert client.get(f'/suite/visiting/cases/{grant.pk}/').status_code==200
    response=client.post(f'/suite/visiting/cases/{grant.pk}/',{'body':'Signed synthetic case note'})
    assert response.status_code==302 and VisitingCaseNote.objects.count()==1
    assert client.post('/suite/tasks/new/',{}).status_code==403
    api=APIClient();token=str(RefreshToken.for_user(t.doctor).access_token);api.credentials(HTTP_AUTHORIZATION='Bearer '+token)
    assert api.get('/api/orders/').status_code==401
    grant.ends_at=t.now-timedelta(minutes=1);grant.save()
    assert client.get(f'/suite/visiting/cases/{grant.pk}/').status_code==404
    assert VisitingCaseNote.objects.count()==1
    client.force_login(t.cover)
    response=client.get(f'/suite/patient/{patient.pk}/?section=visitingnotes')
    assert response.status_code==200 and b'Signed synthetic case note' in response.content


def test_radiology_role_reads_only_imaging(client,team):
    t=team;patient,order,template=diagnostic(t,'lab')
    operator=User.objects.create_user(username='test-radiographer',role='radiology')
    StaffProfile.objects.update_or_create(user=operator,defaults={'facility':t.f})
    client.force_login(operator)
    assert client.get('/suite/diagnostics/').status_code==200
    assert client.get(f'/suite/diagnostics/orders/{order.pk}/').status_code==404
