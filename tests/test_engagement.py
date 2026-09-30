import uuid
from datetime import timedelta
from django.core import signing
from django.utils import timezone
import pytest
from apps.demographics.models import Patient
from apps.operations.models import PortalGrant, PortalRecipient, AppointmentRequest, PatientRecall
from apps.appointments.models import Appointment
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


def portal(t,verified=True):
    patient=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Portal',gender='F')
    grant=PortalGrant.objects.create(patient=patient,created_by=t.reception,expires_at=t.now+timedelta(hours=2))
    if verified:PortalRecipient.objects.create(grant=grant,recipient_name='Verified patient',relationship='patient',verification_reference='In-person verification recorded',allow_appointment_requests=True,created_by=t.reception)
    token=signing.dumps({'p':patient.pk,'g':str(grant.key)},salt='patient-portal')
    return patient,grant,'/portal/'+token


def test_verified_patient_request_retry_booking_and_revocation(client,team):
    t=team;patient,grant,url=portal(t)
    payload={'preferred_date':timezone.localdate()+timedelta(days=2),'reason':'Follow-up appointment','request_key':uuid.uuid4()}
    assert client.post(url,payload).status_code==302
    assert client.post(url,payload).status_code==302 and AppointmentRequest.objects.count()==1
    obj=AppointmentRequest.objects.get();client.force_login(t.reception)
    data={'decision':'booked','clinician':t.doctor.pk,'scheduled_for':t.now+timedelta(days=2),'duration_minutes':30,'response_note':'Confirmed time; please arrive early'}
    assert client.post(f'/suite/appointment-requests/{obj.pk}/',data).status_code==302
    assert client.post(f'/suite/appointment-requests/{obj.pk}/',data).status_code==302 and Appointment.objects.count()==1
    client.logout();assert b'Confirmed time' in client.get(url).content
    grant.revoked_at=timezone.now();grant.save()
    assert client.post(url,payload).status_code==403


def test_legacy_readonly_link_cannot_request_or_escalate(client,team):
    t=team;patient,grant,url=portal(t,False)
    assert client.get(url).status_code==200
    assert client.post(url,{'preferred_date':timezone.localdate(),'reason':'Hello','request_key':uuid.uuid4()}).status_code==403
    client.force_login(t.reception)
    bad={'scopes':['visits','results','appointments'],'allow_appointment_requests':'on','recipient_name':'Guardian','relationship':'guardian','verification_reference':'Verified','verified':'on'}
    assert client.post(f'/portal/token?patient_id={patient.pk}',bad).status_code==200
    assert PortalRecipient.objects.count()==0
    good={**bad,'authority_reference':'Approved guardian authority reference'}
    assert client.post(f'/portal/token?patient_id={patient.pk}',good).status_code==200
    assert PortalRecipient.objects.count()==1


def test_request_patient_and_facility_scopes(client,team):
    t=team;patient,grant,url=portal(t)
    obj=AppointmentRequest.objects.create(grant=grant,patient=patient,preferred_date=timezone.localdate()+timedelta(days=1),reason='Synthetic')
    client.force_login(t.outsider)
    assert client.get(f'/suite/appointment-requests/{obj.pk}/').status_code in (403,404)
    client.force_login(t.reception)
    assert client.get('/suite/appointment-requests/').status_code==200
    assert client.get('/suite/recalls/').status_code==200


def test_recurring_recall_completion_is_idempotent(client,team):
    t=team;patient,grant,url=portal(t)
    obj=PatientRecall.objects.create(patient=patient,owner=t.doctor,purpose='Facility-prescribed follow-up',due_on=timezone.localdate(),repeat_days=30,created_by=t.doctor)
    client.force_login(t.nurse)
    assert client.post(f'/suite/recalls/{obj.pk}/action/',{'decision':'completed','reason':'Done'}).status_code==403
    client.force_login(t.doctor)
    for _ in range(2):assert client.post(f'/suite/recalls/{obj.pk}/action/',{'decision':'completed','reason':'Reviewed patient'}).status_code==302
    obj.refresh_from_db();assert obj.next_recall and PatientRecall.objects.count()==2
    assert obj.next_recall.due_on==timezone.localdate()+timedelta(days=30)


def test_appointment_request_post_requires_csrf(team):
    from django.test import Client
    t=team;patient,grant,url=portal(t)
    c=Client(enforce_csrf_checks=True)
    assert c.post(url,{'preferred_date':timezone.localdate(),'reason':'Synthetic','request_key':uuid.uuid4()}).status_code==403
