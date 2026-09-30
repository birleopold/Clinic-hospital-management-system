import base64
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import FacilityAccess, SecurityEvent
from apps.demographics.models import Patient
from common.facility_scope import filter_by_facility
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


def token(device):return f'{totp(device.bin_key):06d}'


@override_settings(REQUIRE_ADMIN_MFA=True)
def test_admin_session_enrollment_replay_and_reset(client,team):
    t=team;t.manager.is_superuser=True;t.manager.set_password('Synthetic-password-123');t.manager.save()
    client.force_login(t.manager)
    assert client.get('/suite/').url=='/accounts/mfa/'
    assert client.post('/suite/tasks/new/',{}).status_code==403
    assert client.post('/accounts/mfa/enroll/',{'password':'wrong'}).status_code==200
    assert not TOTPDevice.objects.exists()
    assert client.post('/accounts/mfa/enroll/',{'password':'Synthetic-password-123'}).status_code==302
    device=TOTPDevice.objects.get();code=token(device)
    response=client.get('/accounts/mfa/enroll/')
    assert response.status_code==200 and 'no-store' in response['Cache-Control']
    assert client.post('/accounts/mfa/enroll/',{'token':code}).status_code==302
    device.refresh_from_db();assert device.confirmed
    assert client.get('/suite/').status_code==200
    client.logout();client.force_login(t.manager)
    assert client.post('/accounts/mfa/',{'token':code}).status_code==200
    assert client.get('/suite/').status_code==302
    call_command('reset_staff_mfa',t.manager.username,operator=t.manager.username,reason='Verified synthetic recovery',commit=True)
    assert not TOTPDevice.objects.exists()
    assert client.get('/suite/').url=='/accounts/mfa/'
    assert SecurityEvent.objects.filter(event='mfa_server_reset').exists()


@override_settings(REQUIRE_ADMIN_MFA=True)
def test_api_old_token_denial_verified_refresh_and_revocation(client,team):
    t=team;t.manager.role='admin';t.manager.set_password('Synthetic-password-123');t.manager.save()
    device=TOTPDevice.objects.create(user=t.manager,confirmed=True)
    old=RefreshToken.for_user(t.manager)
    assert client.get('/api/patients/',HTTP_AUTHORIZATION='Bearer '+str(old.access_token)).status_code==401
    assert client.post('/api/auth/token/refresh/',{'refresh':str(old)}).status_code==401
    response=client.post('/api/auth/token/',{'username':t.manager.username,'password':'Synthetic-password-123','otp_token':token(device)})
    assert response.status_code==200,response.content
    tokens=response.json()
    assert client.get('/api/patients/',HTTP_AUTHORIZATION='Bearer '+tokens['access']).status_code==200
    assert client.post('/api/auth/token/refresh/',{'refresh':tokens['refresh']}).status_code==200
    device.delete()
    assert client.get('/api/patients/',HTTP_AUTHORIZATION='Bearer '+tokens['access']).status_code==401
    assert client.post('/api/auth/token/refresh/',{'refresh':tokens['refresh']}).status_code==401


def test_branch_grants_scope_revocation_and_superuser_selection(client,team):
    t=team;home=Patient.objects.create(first_name='Home',last_name='Patient',gender='F',facility=t.f)
    other=Patient.objects.create(first_name='Other',last_name='Patient',gender='F',facility=t.other)
    client.force_login(t.manager)
    assert client.post('/accounts/facility/',{'facility':t.other.pk}).status_code==200
    grant=FacilityAccess.objects.create(user=t.manager,facility=t.other,expires_at=timezone.now()+timedelta(hours=1),reason='Acting manager',granted_by=t.manager2)
    assert client.post('/accounts/facility/',{'facility':t.other.pk}).status_code==302
    response=client.get('/suite/insights/')
    assert response.status_code==200
    assert list(filter_by_facility(Patient.objects.all(),response.wsgi_request.user))==[other]
    grant.revoked_at=timezone.now();grant.save()
    assert client.get('/suite/').status_code==403
    assert client.post('/accounts/facility/',{'facility':t.f.pk}).status_code==302
    assert client.get('/suite/').status_code==200
    t.manager.is_superuser=True;t.manager.save()
    assert client.post('/accounts/facility/',{'facility':t.other.pk}).status_code==302
    response=client.get('/suite/insights/')
    assert list(filter_by_facility(Patient.objects.all(),response.wsgi_request.user))==[other]
    assert client.post('/accounts/facility/',{'facility':''}).status_code==302
    response=client.get('/suite/insights/')
    assert filter_by_facility(Patient.objects.all(),response.wsgi_request.user).count()==2


def test_jwt_branch_header_rechecks_grants(client,team):
    t=team;access=str(RefreshToken.for_user(t.manager).access_token)
    args={'HTTP_AUTHORIZATION':'Bearer '+access,'HTTP_X_CLINIC_FACILITY':str(t.other.pk)}
    assert client.get('/api/patients/',**args).status_code==401
    FacilityAccess.objects.create(user=t.manager,facility=t.other,expires_at=timezone.now()+timedelta(hours=1),reason='Manager cover',granted_by=t.manager2)
    assert client.get('/api/patients/',**args).status_code==200


def test_labour_trends_use_current_amendments_and_enforce_scope(client,team):
    from apps.operations.models import Pregnancy, LabourObservation
    t=team;p=Patient.objects.create(first_name='Synthetic',last_name='Maternity',gender='F',facility=t.f)
    pregnancy=Pregnancy.objects.create(patient=p,gravida=1,parity=0,estimated_due_date=timezone.localdate()+timedelta(days=20),assessment='Synthetic record',created_by=t.doctor)
    original=LabourObservation.objects.create(pregnancy=pregnancy,observed_at=t.now,fetal_heart_rate=130,findings='Recorded',plan='Review',created_by=t.doctor)
    correction=LabourObservation.objects.create(pregnancy=pregnancy,observed_at=t.now,fetal_heart_rate=140,supersedes=original,amendment_reason='Corrected source entry',findings='Corrected',plan='Review',created_by=t.doctor)
    client.force_login(t.doctor);response=client.get(f'/suite/pregnancies/{pregnancy.pk}/trends/')
    assert response.status_code==200 and response.context['rows']==[correction]
    assert response.context['panels'][1]['points'][0]['value']==140
    client.force_login(t.reception);assert client.get(f'/suite/pregnancies/{pregnancy.pk}/trends/').status_code==403
    t.outsider.role='clinician';t.outsider.save();client.force_login(t.outsider)
    assert client.get(f'/suite/pregnancies/{pregnancy.pk}/trends/').status_code==404
