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

SUPPORT_RESTRICTED_PREFIXES=(
    '/admin/', '/accounts/password', '/accounts/mfa/',
    '/accounts/staff/', '/accounts/approvals/', '/accounts/tenants/',
)

def is_owner_support(user):
    """A support identity remains temporary, even outside its marked session."""
    if not getattr(user,'is_authenticated',False):return False
    if hasattr(user,'_owner_support_account'):return user._owner_support_account
    from apps.accounts.models import OwnerSupportReceipt
    user._owner_support_account=OwnerSupportReceipt.objects.filter(user=user).exists()
    return user._owner_support_account

def require_permanent_administrator(user):
    """Support tickets never delegate permanent identity/authority management."""
    from django.core.exceptions import PermissionDenied
    if is_owner_support(user) or not user.is_active or not (user.is_superuser or user.role=='admin'):
        raise PermissionDenied('Permanent access changes require a tenant administrator.')

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
        if request.user.is_authenticated:
            support=OwnerSupportReceipt.objects.filter(user=request.user).first()
            request.user._owner_support_account=bool(support)
            if support:
                if request.session.get('owner_support_receipt')!=support.pk or support.revoked_at or support.expires_at<=timezone.now():logout(request)
                else:receipt=support;request.user._trusted_owner_support=True
            elif request.session.get('owner_support_receipt'):logout(request)
        if receipt and request.path.startswith(SUPPORT_RESTRICTED_PREFIXES):
            return HttpResponse('Owner support uses the audited tenant workspace. Permanent credentials and system administration require the tenant administrator.',status=403)
        exempt=request.path in ('/accounts/support/accept/','/accounts/logout/') or request.path.startswith('/static/')
        if not receipt and not exempt and not policy_active():
            return HttpResponse('This tenant is suspended or its owner policy is unavailable. Contact the system owner.',status=503)
        return self.get_response(request)
