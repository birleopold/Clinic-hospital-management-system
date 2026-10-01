"""Production-only isolated tenant process; never route multiple tenants in one DB."""
from .prod import *
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlsplit
import uuid
TENANT_KEY=env('TENANT_KEY')
try:uuid.UUID(TENANT_KEY)
except ValueError:raise ImproperlyConfigured('TENANT_KEY must identify the registered isolated deployment.')
TENANT_SUPPORT_SECRET=env('TENANT_SUPPORT_SECRET')
TENANT_CONTROL_ORIGIN=env('TENANT_CONTROL_ORIGIN').rstrip('/')
p=urlsplit(TENANT_CONTROL_ORIGIN)
if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path:raise ImproperlyConfigured('Use a trusted HTTPS owner origin.')
if len(TENANT_SUPPORT_SECRET)<50:raise ImproperlyConfigured('Owner support requires a unique strong key.')
if not REQUIRE_ADMIN_MFA:raise ImproperlyConfigured('Tenant administrators require MFA.')
OWNER_CONTROL_PLANE=False
SESSION_COOKIE_NAME='clinic_'+uuid.UUID(TENANT_KEY).hex
SESSION_COOKIE_DOMAIN=None
CSRF_COOKIE_DOMAIN=None
MEDIA_ROOT=Path(env('TENANT_MEDIA_ROOT',default='/app/media'))
if not MEDIA_ROOT.is_absolute():raise ImproperlyConfigured('TENANT_MEDIA_ROOT must be absolute.')
