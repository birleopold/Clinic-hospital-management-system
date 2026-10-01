"""Disposable three-process HTTPS verification; never connects to an existing DB.

Requires Node/playwright/axe-core and Chromium. No production credentials needed.
Each independent application gets a fresh physical SQLite database, private media
and signing keys. PostgreSQL and Compose deployment remain separate CI/host gates.
"""
import json,os,secrets,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SETTINGS='''from config.settings.base import *
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ['REVIEW_DATABASE']}}
MEDIA_ROOT=Path(os.environ['REVIEW_MEDIA'])
STATIC_ROOT=Path(os.environ['REVIEW_STATIC'])
DEBUG=False
ALLOWED_HOSTS=['127.0.0.1','127.0.0.2','127.0.0.3']
CSRF_TRUSTED_ORIGINS=['https://127.0.0.1:8443','https://127.0.0.2:8443','https://127.0.0.3:8443']
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_NAME='review_'+(TENANT_KEY or 'owner').replace('-','')
SESSION_COOKIE_DOMAIN=None
CSRF_COOKIE_DOMAIN=None
PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
MIDDLEWARE.insert(1,'whitenoise.middleware.WhiteNoiseMiddleware')
TIME_ZONE='UTC'
'''
SERVER='''import os,ssl
from wsgiref.simple_server import make_server,WSGIRequestHandler
from config.wsgi import application
class Handler(WSGIRequestHandler):
    def log_message(self,*args):pass
    def get_environ(self):
        e=super().get_environ();e['HTTPS']='on';return e
server=make_server(os.environ['REVIEW_HOST'],8443,application,handler_class=Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(os.environ['REVIEW_CERT'],os.environ['REVIEW_CERT_KEY'])
server.socket=context.wrap_socket(server.socket,server_side=True);server.serve_forever()
'''
ROOT_SEED='''import django,json,os,secrets
django.setup()
from apps.accounts.models import User,Facility,StaffProfile,FacilityConfiguration
from apps.accounts import tenant_services as service
from django_otp.plugins.otp_totp.models import TOTPDevice
from common.service_policy import SERVICES
owner=User.objects.create_user('review-owner',password=os.environ['REVIEW_PASSWORD'],role='admin',is_superuser=True,is_staff=True,mfa_required=True)
f=Facility.objects.create(name='Synthetic control facility');StaffProfile.objects.create(user=owner,facility=f)
FacilityConfiguration.objects.create(facility=f,display_name=f.name,service_type='hospital',enabled_services=list(SERVICES),configured_by=owner)
manager=User.objects.create_user('review-manager',role='manager');StaffProfile.objects.create(user=manager,facility=f)
otp=secrets.token_hex(20);TOTPDevice.objects.create(user=owner,key=otp,confirmed=True)
data={'password':os.environ['REVIEW_PASSWORD'],'owner_otp':otp,'facility':f.pk,'manager':manager.pk,'tenants':[]}
for i,name in [(2,'Alpha'),(3,'Beta')]:
    obj=service.create(owner,name='Synthetic '+name,origin='https://127.0.0.'+str(i)+':8443',bind_port=18000+i,admin_username='tenant-admin',service_type='hospital',services=list(SERVICES))
    data['tenants'].append({'name':name,'key':str(obj.key),'pk':obj.pk,'origin':obj.origin,'secrets':service.secrets_for(obj)})
from pathlib import Path
Path(os.environ['REVIEW_FIXTURE']).write_text(json.dumps(data))
'''
TENANT_SEED='''import django,json,os,secrets
from pathlib import Path
django.setup()
from django.core.management import call_command
from django.core import signing
from django_otp.plugins.otp_totp.models import TOTPDevice
from apps.accounts.models import User,Facility
from apps.inventory.models import InventoryItem,Supplier
from apps.billing.models import PriceList,PriceListItem
from apps.demographics.models import Patient
from apps.operations.models import PortalGrant
from django.utils import timezone
from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken
call_command('bootstrap_tenant')
u=User.objects.get(username='tenant-admin');key=secrets.token_hex(20);device=TOTPDevice.objects.create(user=u,key=key,confirmed=True)
name=os.environ['REVIEW_NAME'];f=Facility.objects.get()
InventoryItem.objects.create(code='SAME-CODE',name=name+' private medicine')
Supplier.objects.create(name=name+' private supplier')
pl=PriceList.objects.create(name=name+' private prices');PriceListItem.objects.create(pricelist=pl,code='SAME-CODE',name=name,amount=111 if name=='Alpha' else 222)
p=Patient.objects.create(facility=f,first_name=name,last_name='Synthetic patient',gender='F')
grant=PortalGrant.objects.create(patient=p,created_by=u,expires_at=timezone.now()+timedelta(hours=1))
portal=signing.dumps({'p':p.pk,'g':str(grant.key)},salt='patient-portal')
refresh=RefreshToken.for_user(u);refresh['mfa_device_id']=device.pk
Path(os.environ['REVIEW_RESULT']).write_text(json.dumps({'otp':key,'jwt':str(refresh.access_token),'portal':portal,'patient':p.pk,'item':1}))
Path(os.environ['REVIEW_MEDIA']).mkdir(exist_ok=True);Path(os.environ['REVIEW_MEDIA'],'private.txt').write_text(name+' private media')
'''

def run():
    with tempfile.TemporaryDirectory(prefix='clinic-tenant-review-') as temp:
        temp=Path(temp);(temp/'tenant_review_settings.py').write_text(SETTINGS);(temp/'server.py').write_text(SERVER)
        cert=temp/'cert.pem';cert_key=temp/'cert-key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(cert_key),'-out',str(cert),'-days','1','-subj','/CN=Disposable clinic review','-addext','subjectAltName=IP:127.0.0.1,IP:127.0.0.2,IP:127.0.0.3','-addext','basicConstraints=critical,CA:TRUE'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        fixture=temp/'fixture.json'
        env={**os.environ,'PYTHONPATH':str(temp)+os.pathsep+str(ROOT),'DJANGO_SETTINGS_MODULE':'tenant_review_settings','DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'OWNER_CONTROL_PLANE':'1','TENANT_KEY':'','TENANT_PUBLIC_ORIGIN':'https://127.0.0.1:8443','REVIEW_DATABASE':str(temp/'baseline.sqlite3'),'REVIEW_MEDIA':str(temp/'owner-media'),'REVIEW_STATIC':str(temp/'static'),'REVIEW_PASSWORD':'Synthetic-HTTPS-Review-789!','REVIEW_FIXTURE':str(fixture),'REVIEW_CERT':str(cert),'REVIEW_CERT_KEY':str(cert_key),'SSL_CERT_FILE':str(cert),'NO_PROXY':'127.0.0.1,127.0.0.2,127.0.0.3','REQUIRE_ADMIN_MFA':'1','REQUIRE_SERVICE_SETUP':'1'}
        def command(args,e=env):subprocess.run([sys.executable,*args],cwd=ROOT,env=e,check=True,stdout=subprocess.DEVNULL)
        command(['manage.py','migrate','--noinput']);command(['manage.py','collectstatic','--noinput'])
        for name in ('owner','Alpha','Beta'):shutil.copy2(temp/'baseline.sqlite3',temp/(name+'.sqlite3'))
        env['REVIEW_DATABASE']=str(temp/'owner.sqlite3');env['REVIEW_HOST']='127.0.0.1'
        command(['-c',ROOT_SEED]);data=json.loads(fixture.read_text());servers=[]
        try:
            servers.append(subprocess.Popen([sys.executable,str(temp/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            for i,item in enumerate(data['tenants'],2):
                tenant_env={**env,'OWNER_CONTROL_PLANE':'0','TENANT_KEY':item['key'],'TENANT_SUPPORT_SECRET':item['secrets']['support'],'DJANGO_SECRET_KEY':item['secrets']['django'],'TENANT_CONTROL_ORIGIN':'https://127.0.0.1:8443','REVIEW_DATABASE':str(temp/(item['name']+'.sqlite3')),'REVIEW_HOST':'127.0.0.'+str(i),'REVIEW_MEDIA':str(temp/(item['name']+'-media')),'REVIEW_NAME':item['name'],'REVIEW_RESULT':str(temp/(item['name']+'.json')),'TENANT_ADMIN_USERNAME':'tenant-admin','TENANT_ADMIN_PASSWORD':data['password'],'TENANT_BOOTSTRAP':json.dumps({'name':'Synthetic '+item['name'],'service_type':'hospital','services':['patients','clinical','appointments','pharmacy','inventory','billing','lab','imaging','inpatient','maternity','theatre','vaccination','rehabilitation','programmes','engagement','workforce','management']})}
                command(['-c',TENANT_SEED],tenant_env)
                item.update(json.loads(Path(tenant_env['REVIEW_RESULT']).read_text()));item.pop('secrets')
                servers.append(subprocess.Popen([sys.executable,str(temp/'server.py')],cwd=ROOT,env=tenant_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            assert (temp/'Alpha-media/private.txt').read_text()!='Beta private media'
            assert (temp/'Alpha.sqlite3').stat().st_ino!=(temp/'Beta.sqlite3').stat().st_ino
            fixture.write_text(json.dumps(data));subprocess.run(['node',str(ROOT/'scripts/tenant_control_browser.cjs')],cwd=ROOT,env={**env,'CLINIC_TENANT_FIXTURE':str(fixture)},check=True)
        finally:
            for process in servers:process.terminate()
            for process in servers:
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
if __name__=='__main__':run()
