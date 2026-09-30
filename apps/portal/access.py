"""Shared patient-link authorization for every portal action and download."""
from django.core import signing
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from apps.operations.models import PortalGrant, PortalRecipient

SCOPES = [('visits','Visit summary'),('results','Released diagnostic results'),('medicines','Prescriptions'),('billing','Invoices'),('appointments','Appointment requests and changes'),('feedback','Feedback intake'),('instructions','Approved service preparation instructions')]
LEGACY = {'visits','results','medicines','billing'}


def authorize(token, scope=None, lock=False):
    try:
        data=signing.loads(token,salt='patient-portal',max_age=getattr(settings,'PATIENT_PORTAL_TOKEN_MAX_AGE',72*3600))
        qs=PortalGrant.objects.select_related('patient')
        if lock:qs=qs.select_for_update()
        grant=qs.get(key=data.get('g'),patient_id=data.get('p'),revoked_at__isnull=True,expires_at__gt=timezone.now(),patient__merged_into__isnull=True)
    except (signing.BadSignature,PortalGrant.DoesNotExist,ValueError,TypeError,AttributeError):
        raise PermissionDenied('Invalid, expired or revoked patient link.')
    recipient=PortalRecipient.objects.filter(grant=grant).first()
    scopes=set(recipient.scopes) if recipient and recipient.scopes else set(LEGACY)
    if recipient and recipient.allow_appointment_requests and (not recipient.scopes or 'appointments' in scopes):scopes.add('appointments')
    if recipient and not recipient.allow_appointment_requests:scopes.discard('appointments')
    from apps.accounts.models import FacilityConfiguration
    conf=FacilityConfiguration.objects.filter(facility_id=grant.patient.facility_id).first()
    if conf:
        services=set(conf.enabled_services)
        requirements={'visits':{'clinical'},'results':{'lab','imaging'},'medicines':{'clinical','pharmacy'},'billing':{'billing'},'appointments':{'appointments'},'feedback':{'management'},'instructions':{'lab','imaging','clinical'}}
        scopes={key for key in scopes if services & requirements.get(key,set())}
        if 'engagement' not in services:scopes.discard('appointments');scopes.discard('feedback')
    if scope and scope not in scopes:raise PermissionDenied('This patient link does not authorize that action.')
    return grant,recipient,scopes


def diagnostic_types(grant):
    from apps.accounts.models import FacilityConfiguration
    conf=FacilityConfiguration.objects.filter(facility_id=grant.patient.facility_id).first()
    if not conf:return ['lab','imaging','procedure']
    return [kind for kind,service in [('lab','lab'),('imaging','imaging'),('procedure','clinical')] if service in conf.enabled_services]
