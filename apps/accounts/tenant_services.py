import base64,hashlib,io,json,secrets,zipfile
from urllib.parse import urlsplit
from cryptography.fernet import Fernet,MultiFernet
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.core import signing
from .models import TenantDeployment,User
from common.mfa import record
from common.service_policy import SERVICES,PRESETS,DEPENDENCIES

def owner(actor):
    if not actor.is_active or not actor.is_superuser or not getattr(settings,'OWNER_CONTROL_PLANE',False) or getattr(settings,'TENANT_KEY',''):raise PermissionDenied

def origin(value):
    from django.core.validators import URLValidator
    URLValidator(schemes=['https'])(value)
    try:
        p=urlsplit(value);port=p.port
    except ValueError:raise ValidationError('Use a valid HTTPS origin.')
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
        raise ValidationError('Use an HTTPS origin without paths, credentials, queries or fragments.')
    host=p.hostname.lower()
    if ':' in host:host='['+host+']'
    return 'https://'+host+(':'+str(port) if port and port!=443 else '')

def vault():
    keys=[settings.SECRET_KEY]+list(getattr(settings,'SECRET_KEY_FALLBACKS',[]))
    return MultiFernet([Fernet(base64.urlsafe_b64encode(hashlib.sha256(('tenant-vault:'+key).encode()).digest())) for key in keys])

def secrets_for(obj):return json.loads(vault().decrypt(obj.secret_envelope.encode()))

@transaction.atomic
def create(actor,**data):
    owner(actor);data['origin']=origin(data['origin'])
    if not 1024<=data['bind_port']<=65535:raise ValidationError('Choose a private application port from 1024–65535.')
    if data['service_type'] not in PRESETS or not data['services'] or set(data['services'])-set(SERVICES):raise ValidationError('Choose a supported preset and services.')
    User._meta.get_field('username').run_validators(data['admin_username'])
    active=set(data['services']);data['services']=sorted(active)
    for service in active:
        if set(DEPENDENCIES.get(service,[]))-active:raise ValidationError('Include all dependencies of the selected services.')
    if data['origin']==origin(settings.TENANT_PUBLIC_ORIGIN):raise ValidationError('Use a different tenant hostname from the owner console.')
    secret={'django':secrets.token_urlsafe(64),'database':secrets.token_hex(32),'support':secrets.token_urlsafe(64),'admin_password':secrets.token_urlsafe(24)}
    obj=TenantDeployment(**data,created_by=actor,secret_envelope=vault().encrypt(json.dumps(secret).encode()).decode())
    obj.full_clean();obj.save();record(actor,'tenant_registered',str(obj.key))
    return obj

@transaction.atomic
def state(actor,pk,decision,revision,reason):
    owner(actor)
    obj=TenantDeployment.objects.select_for_update().get(pk=pk)
    if obj.revision!=revision:raise ValidationError('Tenant changed. Reload before applying policy.')
    if decision not in ('active','suspended') or not reason.strip():raise ValidationError('Choose resume/suspend and record a reason.')
    if decision=='active' and not obj.last_seen_at:raise ValidationError('Deploy the tenant and receive its authenticated heartbeat first.')
    obj.state=decision;obj.revision+=1;obj.save(update_fields=['state','revision'])
    record(actor,'tenant_policy_changed',f'{obj.key}; {decision}; {reason}'[:250]);return obj

def support_ticket(actor,obj,reason):
    owner(actor)
    if not obj.last_seen_at or not reason.strip():raise ValidationError('A deployed tenant and support reason are required.')
    record(actor,'tenant_support_started',f'{obj.key}; {reason}'[:250])
    return signing.dumps({'tenant':str(obj.key),'nonce':str(__import__('uuid').uuid4()),'owner':str(actor.pk),'reason':reason[:250]},key=secrets_for(obj)['support'],salt='tenant-owner-support')

def bundle(actor,obj):
    owner(actor);s=secrets_for(obj)
    env={'DJANGO_SETTINGS_MODULE':'config.settings.tenant','DJANGO_SECRET_KEY':s['django'],'DJANGO_DEBUG':'0','DJANGO_ALLOWED_HOSTS':urlsplit(obj.origin).hostname,'DJANGO_CSRF_TRUSTED_ORIGINS':obj.origin,'TENANT_KEY':str(obj.key),'TENANT_SUPPORT_SECRET':s['support'],'TENANT_CONTROL_ORIGIN':origin(settings.TENANT_PUBLIC_ORIGIN),'TENANT_DB_PASSWORD':s['database'],'DATABASE_URL':'postgres://hms:'+s['database']+'@database:5432/hms','TENANT_ADMIN_USERNAME':obj.admin_username,'TENANT_ADMIN_PASSWORD':s['admin_password'],'TENANT_BOOTSTRAP':json.dumps({'name':obj.name,'service_type':obj.service_type,'services':obj.services},separators=(',',':')),'CELERY_BROKER_URL':'redis://redis:6379/0','CELERY_RESULT_BACKEND':'redis://redis:6379/1','REQUIRE_ADMIN_MFA':'1','REQUIRE_SERVICE_SETUP':'1','DJANGO_USE_X_FORWARDED_PROTO':'1','DJANGO_SECURE_SSL_REDIRECT':'1','TENANT_BIND_PORT':str(obj.bind_port)}
    # Single-quoted dotenv values remain literal, including dollar expressions.
    # Compose supports escaped apostrophes inside these quotes.
    env_text=''.join(key+"='"+value.replace("'", "\\'")+"'\n" for key,value in env.items())
    from pathlib import Path
    template=(settings.BASE_DIR/'deploy/tenants/compose.yaml').read_text()
    compose='name: clinic-'+obj.key.hex+'\n'+template
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('.env',env_text)
        archive.writestr('compose.yaml',compose)
        archive.writestr('README.txt','Protect this bundle: it contains tenant credentials. Build clinic-hms:tenant-v1 from the reviewed repository Dockerfile first. Place this bundle in its own protected directory (chmod 700 directory, chmod 600 .env). Run docker compose up -d. Route ONLY '+obj.origin+' through a trusted HTTPS reverse proxy to 127.0.0.1:'+str(obj.bind_port)+'. Do not expose PostgreSQL, Redis or private media. Log in with TENANT_ADMIN_USERNAME / TENANT_ADMIN_PASSWORD from .env, change the bootstrap password, enroll MFA, and review configuration. Tenant activation occurs only after its authenticated policy heartbeat. Suspend/resume and support are managed from the owner console. Keep separate database/media backups per tenant. Do not reuse the bundle for another business. Re-download preserves keys; rotating keys requires a planned migration.\n')
    record(actor,'tenant_bundle_downloaded',str(obj.key));return out.getvalue()
