import io
import json
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from apps.accounts.models import User, TenantDeployment, OwnerSupportReceipt, Facility, FacilityConfiguration
from apps.accounts import tenant_services as service
from common import tenant_runtime

pytestmark=pytest.mark.django_db

@pytest.fixture
def owner_settings(settings):
    settings.OWNER_CONTROL_PLANE=True
    settings.TENANT_KEY=''
    settings.TENANT_PUBLIC_ORIGIN='https://owner.example.test'
    cache.clear()
    return User.objects.create_user('platform-owner',is_superuser=True,role='admin')

def registration(**kwargs):
    return dict(name='Synthetic clinic',origin='https://clinic.example.test',bind_port=18001,admin_username='administrator',service_type='custom',services=['patients'],**kwargs)

def token(obj):
    return signing.dumps({'tenant':str(obj.key),'nonce':str(uuid.uuid4())},key=service.secrets_for(obj)['support'],salt='tenant-policy-request')

def test_registration_bundle_and_duplicate_ui(client,owner_settings):
    owner=owner_settings;client.force_login(owner)
    data=registration()
    assert client.post('/accounts/tenants/',data).status_code==302
    obj=TenantDeployment.objects.get()
    assert client.post('/accounts/tenants/',data).status_code==200
    assert TenantDeployment.objects.count()==1
    response=client.post(f'/accounts/tenants/{obj.pk}/',{'action':'bundle'})
    assert response.status_code==200
    assert 'no-store' in response['Cache-Control']
    archive=zipfile.ZipFile(io.BytesIO(response.content))
    env=dict(line.split('=',1) for line in archive.read('.env').decode().splitlines())
    env={k:v[1:-1].replace("\\'", "'") for k,v in env.items()}
    secrets=service.secrets_for(obj)
    assert secrets['django'] not in obj.secret_envelope
    assert env['TENANT_KEY']==str(obj.key)
    assert env['DJANGO_SECRET_KEY']==secrets['django']
    assert env['TENANT_SUPPORT_SECRET']==secrets['support']
    assert json.loads(env['TENANT_BOOTSTRAP'])['services']==['patients']
    assert 'name: clinic-'+obj.key.hex in archive.read('compose.yaml').decode()
    assert b'127.0.0.1:${TENANT_BIND_PORT}' in archive.read('compose.yaml')
    page=client.get('/accounts/tenants/').content.decode()
    assert secrets['admin_password'] not in page and secrets['support'] not in page
    assert zipfile.ZipFile(io.BytesIO(service.bundle(owner,obj))).read('.env')==archive.read('.env')
    second=service.create(owner,**{**data,'origin':'https://second.example.test','bind_port':18002})
    assert service.secrets_for(second)!=secrets
    assert second.key!=obj.key
    with pytest.raises(ValidationError):service.create(owner,**{**data,'origin':'https://owner.example.test','bind_port':18003})
    client.force_login(User.objects.create_user('tenant-admin',role='admin'))
    assert client.get('/accounts/tenants/').status_code==403
    with override_settings(TENANT_KEY=str(obj.key)):
        with pytest.raises(PermissionDenied):service.bundle(owner,obj)

def test_signed_heartbeat_suspension_and_optimistic_policy(client,owner_settings):
    obj=service.create(owner_settings,**registration())
    secret=service.secrets_for(obj)['support']
    with pytest.raises(ValidationError):service.state(owner_settings,obj.pk,'active',obj.revision,'Ready')
    response=client.get('/accounts/tenants/policy/',{'ticket':token(obj)})
    assert response.status_code==200
    assert signing.loads(response.content.decode(),key=secret,salt='tenant-policy-response',fallback_keys=[])['active']
    obj.refresh_from_db();assert obj.state=='active' and obj.last_seen_at
    old=obj.revision
    obj=service.state(owner_settings,obj.pk,'suspended',old,'Maintenance')
    with pytest.raises(ValidationError):service.state(owner_settings,obj.pk,'active',old,'Stale')
    response=client.get('/accounts/tenants/policy/',{'ticket':token(obj)})
    assert not signing.loads(response.content.decode(),key=secret,salt='tenant-policy-response',fallback_keys=[])['active']
    wrong=signing.dumps({'tenant':str(obj.key)},key='another-tenant-key',salt='tenant-policy-request')
    assert client.get('/accounts/tenants/policy/',{'ticket':wrong}).status_code==403

def test_owner_support_single_use_audience_mfa_and_revocation(client,owner_settings,settings):
    obj=service.create(owner_settings,**registration())
    obj.last_seen_at=timezone.now();obj.save()
    ticket=service.support_ticket(owner_settings,obj,'Investigate synthetic support request')
    secret=service.secrets_for(obj)['support']
    admin=User.objects.create_user('tenant-admin',role='admin')
    with override_settings(TENANT_KEY=str(uuid.uuid4()),TENANT_SUPPORT_SECRET=secret):
        assert client.post('/accounts/support/accept/',{'ticket':ticket}).status_code==403
    with override_settings(TENANT_KEY=str(obj.key),TENANT_SUPPORT_SECRET=secret,OWNER_CONTROL_PLANE=False,REQUIRE_ADMIN_MFA=True),patch.object(tenant_runtime,'policy_active',return_value=True):
        assert client.post('/accounts/support/accept/',{'ticket':ticket}).status_code==302
        assert client.get('/accounts/control/').status_code==200
        receipt=OwnerSupportReceipt.objects.get()
        assert not receipt.user.has_usable_password()
        assert client.get('/accounts/tenants/').status_code==403
        assert client.post('/accounts/support/accept/',{'ticket':ticket}).status_code==403
        assert OwnerSupportReceipt.objects.count()==1
        receipt.revoked_at=timezone.now();receipt.save()
        assert client.get('/accounts/control/').status_code==302
        assert '_auth_user_id' not in client.session
    with override_settings(TENANT_KEY=str(obj.key),TENANT_SUPPORT_SECRET=secret,OWNER_CONTROL_PLANE=False),patch.object(tenant_runtime,'policy_active',return_value=True):
        client.force_login(admin)
        assert client.get('/accounts/support/sessions/').status_code==200
        assert client.post('/accounts/support/sessions/',{'receipt':receipt.pk}).status_code==302
        client.force_login(User.objects.create_user('regular-staff',role='reception'))
        assert client.get('/accounts/support/sessions/').status_code==403

def test_expired_support_and_secret_fallback_never_authorize(client,owner_settings):
    obj=service.create(owner_settings,**registration());obj.last_seen_at=timezone.now();obj.save()
    secret=service.secrets_for(obj)['support']
    with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()-40):
        ticket=service.support_ticket(owner_settings,obj,'Expired synthetic request')
    payload={'tenant':str(obj.key),'nonce':str(uuid.uuid4()),'owner':'1','reason':'Synthetic'}
    fallback=signing.dumps(payload,key='old-django-secret',salt='tenant-owner-support')
    with override_settings(TENANT_KEY=str(obj.key),TENANT_SUPPORT_SECRET=secret,SECRET_KEY_FALLBACKS=['old-django-secret']),patch.object(tenant_runtime,'policy_active',return_value=True):
        for ticket in (ticket,fallback,'malformed'):
            assert client.post('/accounts/support/accept/',{'ticket':ticket}).status_code==403
    assert not OwnerSupportReceipt.objects.exists()

def test_runtime_failure_is_closed_and_tasks_retry(settings):
    settings.TENANT_KEY=str(uuid.uuid4());settings.TENANT_SUPPORT_SECRET='test-key';settings.TENANT_CONTROL_ORIGIN='https://owner.example.test'
    cache.clear()
    with patch.object(tenant_runtime,'build_opener',side_effect=OSError):
        assert not tenant_runtime.policy_active()
    from celery.exceptions import Retry
    task=tenant_runtime.TenantTask()
    with patch.object(tenant_runtime,'policy_active',return_value=False),patch.object(task,'retry',side_effect=Retry()) as retry:
        with pytest.raises(Retry):task()
        retry.assert_called_once_with(countdown=30,max_retries=None)

def test_bootstrap_idempotent(settings,monkeypatch):
    settings.TENANT_KEY=str(uuid.uuid4())
    monkeypatch.setenv('TENANT_BOOTSTRAP',json.dumps({'name':'Synthetic tenant','service_type':'custom','services':['patients']}))
    monkeypatch.setenv('TENANT_ADMIN_USERNAME','administrator')
    monkeypatch.setenv('TENANT_ADMIN_PASSWORD','Synthetic-Strong-Password-2026')
    call_command('bootstrap_tenant',stdout=io.StringIO())
    call_command('bootstrap_tenant',stdout=io.StringIO())
    assert User.objects.exclude(username='AnonymousUser').count()==1 and Facility.objects.count()==1 and FacilityConfiguration.objects.count()==1
    assert User.objects.get(username='administrator').mfa_required

def test_all_portal_action_paths_redact_bearer():
    from apps.audit.middleware import audit_path
    from django.test import RequestFactory
    for suffix in ('','/feedback/','/appointments/1/change/','/acknowledge/','/revoke/'):
        assert audit_path(RequestFactory().get('/portal/private-bearer'+suffix))=='/portal/<redacted>/'


def test_compose_preserves_literal_bootstrap_and_isolated_network(tmp_path,owner_settings):
    import shutil,subprocess,os
    docker=shutil.which('docker')
    if not docker or subprocess.run([docker,'compose','version'],capture_output=True).returncode:
        pytest.skip('Docker Compose config validation runs on CI hosts with Compose.')
    data=registration();data['name']="O'Connor ${SHOULD_NOT_EXPAND} \\ Clinic"
    obj=service.create(owner_settings,**data)
    archive=zipfile.ZipFile(io.BytesIO(service.bundle(owner_settings,obj)))
    archive.extractall(tmp_path)
    result=subprocess.run([docker,'compose','--env-file','.env','-f','compose.yaml','config','--format','json'],cwd=tmp_path,capture_output=True,text=True,env={**os.environ,'SHOULD_NOT_EXPAND':'unexpected'})
    assert result.returncode==0,'Compose must accept the generated bundle.'
    config=json.loads(result.stdout)
    application=config['services']['application']
    # Compose config escapes dollars for a reloadable serialization of its model.
    bootstrap=application['environment']['TENANT_BOOTSTRAP'].replace('$$','$')
    assert json.loads(bootstrap)['name']==data['name']
    assert application['environment']['TENANT_KEY']==str(obj.key)
    assert application['ports'][0]['host_ip']=='127.0.0.1'
    assert not config['services']['database'].get('ports') and not config['services']['redis'].get('ports')
    assert config['name']=='clinic-'+obj.key.hex


def test_worker_registered_task_uses_tenant_policy():
    from config.celery import app
    app.autodiscover_tasks(force=True)
    assert isinstance(app.tasks['integrations.health_ping'],tenant_runtime.TenantTask)


def test_support_account_cannot_escape_browser_expiry_or_obtain_jwt(client,owner_settings):
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework.test import APIClient
    obj=service.create(owner_settings,**registration());obj.last_seen_at=timezone.now();obj.save()
    ticket=service.support_ticket(owner_settings,obj,'Synthetic boundary check')
    secret=service.secrets_for(obj)['support']
    with override_settings(TENANT_KEY=str(obj.key),TENANT_SUPPORT_SECRET=secret,OWNER_CONTROL_PLANE=False),patch.object(tenant_runtime,'policy_active',return_value=True):
        assert client.post('/accounts/support/accept/',{'ticket':ticket}).status_code==302
        receipt=OwnerSupportReceipt.objects.get()
        for path in ('/admin/','/accounts/password_change/','/accounts/mfa/enroll/'):
            assert client.get(path).status_code==403
        # A changed password does not turn temporary support into a permanent user.
        receipt.user.set_password('Synthetic-Changed-Password-123');receipt.user.save()
        api=APIClient()
        assert api.post('/api/auth/token/',{'username':receipt.user.username,'password':'Synthetic-Changed-Password-123'}).status_code==401
        refresh=RefreshToken.for_user(receipt.user)
        assert api.post('/api/auth/token/refresh/',{'refresh':str(refresh)}).status_code==401
        api.credentials(HTTP_AUTHORIZATION='Bearer '+str(refresh.access_token))
        assert api.get('/api/inventory/items/').status_code==401
        client.force_login(receipt.user)
        assert client.get('/accounts/control/').status_code==302
        assert '_auth_user_id' not in client.session
        # Re-enter a valid marked support session, then let its receipt expire.
        client.force_login(receipt.user);session=client.session;session['owner_support_receipt']=receipt.pk;session.save()
        receipt.expires_at=timezone.now()-timedelta(seconds=1);receipt.save()
        assert client.get('/accounts/control/').status_code==302
        assert '_auth_user_id' not in client.session
