from django.utils import timezone
from django.db.models import Prefetch
from apps.operations.models import PortalGrant
from apps.orders.models import OrderResult
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.orders.models import Order
from apps.pharmacy.models import Prescription
from apps.billing.models import Invoice
from common.facility_scope import filter_by_facility


# Config: default max age 72 hours
MAX_AGE = getattr(settings, 'PATIENT_PORTAL_TOKEN_MAX_AGE', 72 * 3600)
SALT = 'patient-portal'


@never_cache
def portal_view(request, token: str):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        patient_id = int(data.get('p'))
    except Exception:
        return HttpResponseForbidden('Invalid or expired link')

    grant = PortalGrant.objects.filter(key=data.get('g'), patient_id=patient_id, revoked_at__isnull=True, expires_at__gt=timezone.now()).first() if data.get('g') else None
    if not grant:
        return HttpResponseForbidden('Invalid or revoked link')
    patient = get_object_or_404(Patient, pk=patient_id)

    encounters = Encounter.objects.filter(patient=patient).select_related('clinician').order_by('-id')[:50]
    lab_orders = Order.objects.filter(patient=patient, order_type=Order.LAB).prefetch_related(Prefetch('results', queryset=OrderResult.objects.filter(approved_at__isnull=False))).order_by('-id')[:50]
    prescriptions = Prescription.objects.filter(patient=patient).prefetch_related('items').order_by('-id')[:50]
    invoices = Invoice.objects.filter(patient=patient).order_by('-id')[:50]

    context = {
        'token': token,
        'patient': patient,
        'encounters': encounters,
        'lab_orders': lab_orders,
        'prescriptions': prescriptions,
        'invoices': invoices,
    }
    response = render(request, 'portal/view.html', context)
    response['Referrer-Policy'] = 'no-referrer'
    return response


@login_required
@never_cache
def token_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','reception','clinician')):
        return HttpResponseForbidden('Not allowed')

    try:
        patient_id = int(request.GET.get('patient_id') or '0')
    except Exception:
        patient_id = 0
    patient = get_object_or_404(filter_by_facility(Patient.objects.all(), user), pk=patient_id) if patient_id else None

    link = None
    if patient and request.method == 'POST':
        grant = PortalGrant.objects.create(patient=patient, created_by=user, expires_at=timezone.now()+timedelta(seconds=MAX_AGE))
        token = signing.dumps({'p': patient.id, 'g': str(grant.key)}, salt=SALT)
        link = request.build_absolute_uri(reverse('portal-view', args=[token]))

    context = {
        'patient': patient,
        'link': link,
        'max_age_hours': int(MAX_AGE // 3600),
    }
    return render(request, 'portal/token_create.html', context)


@never_cache
def portal_download(request, token, pk):
    from django.http import FileResponse, Http404
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        grant = PortalGrant.objects.get(key=data.get('g'), patient_id=data.get('p'), revoked_at__isnull=True, expires_at__gt=timezone.now())
    except Exception:
        return HttpResponseForbidden('Invalid or expired link')
    result = get_object_or_404(OrderResult, pk=pk, order__patient_id=grant.patient_id, approved_at__isnull=False)
    if not result.attachment:
        raise Http404
    response = FileResponse(result.attachment.open('rb'), as_attachment=True, filename=result.attachment.name.rsplit('/',1)[-1])
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
