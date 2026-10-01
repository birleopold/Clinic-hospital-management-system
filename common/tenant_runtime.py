"""One process/database/key/media namespace per independent tenant."""
import uuid
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponse
from django.contrib.auth import logout
from django.utils import timezone
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler
from celery import Task

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def policy_active():
    key=getattr(settings,'TENANT_KEY','')
    if not key:return True
    cached=cache.get('tenant-policy:'+key)
    if cached is not None:return cached
    try:
        secret=settings.TENANT_SUPPORT_SECRET
        ticket=signing.dumps({'tenant':key,'nonce':str(uuid.uuid4())},key=secret,salt='tenant-policy-request')
        url=settings.TENANT_CONTROL_ORIGIN+'/accounts/tenants/policy/?'+urlencode({'ticket':ticket})
        with build_opener(NoRedirect).open(Request(url,headers={'Accept':'text/plain'}),timeout=3) as response:
            body=response.read(4097)
        if len(body)>4096:return False
        data=signing.loads(body.decode(),key=secret,salt='tenant-policy-response',max_age=15,fallback_keys=[])
        active=data.get('tenant')==key and data.get('active') is True
    except Exception:
        # Missing/expired control policy never opens suspended tenant traffic.
        active=False
    cache.set('tenant-policy:'+key,active,5)
    return active

class TenantTask(Task):
    def __call__(self,*args,**kwargs):
        if not policy_active():raise self.retry(countdown=30, max_retries=None)
        return super().__call__(*args,**kwargs)

class TenantRuntimeMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        from apps.accounts.models import OwnerSupportReceipt
        receipt=None
        if request.user.is_authenticated and request.session.get('owner_support_receipt'):
            receipt=OwnerSupportReceipt.objects.filter(pk=request.session['owner_support_receipt'],user=request.user,revoked_at__isnull=True,expires_at__gt=timezone.now()).first()
            if not receipt:logout(request)
            else:request.user._trusted_owner_support=True
        exempt=request.path in ('/accounts/support/accept/','/accounts/logout/') or request.path.startswith('/static/')
        if not receipt and not exempt and not policy_active():
            return HttpResponse('This tenant is suspended or its owner policy is unavailable. Contact the system owner.',status=503)
        return self.get_response(request)
