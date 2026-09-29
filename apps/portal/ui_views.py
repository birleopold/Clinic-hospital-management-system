from datetime import timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.urls import reverse

from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.orders.models import Order
from apps.pharmacy.models import Prescription
from apps.billing.models import Invoice
from common.facility_scope import filter_by_facility


# Config: default max age 72 hours
MAX_AGE = getattr(settings, 'PATIENT_PORTAL_TOKEN_MAX_AGE', 72 * 3600)
SALT = 'patient-portal'


def portal_view(request, token: str):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        patient_id = int(data.get('p'))
    except Exception:
        return HttpResponseForbidden('Invalid or expired link')

    patient = get_object_or_404(Patient, pk=patient_id)

    encounters = Encounter.objects.filter(patient=patient).select_related('clinician').order_by('-id')[:50]
    lab_orders = Order.objects.filter(patient=patient, order_type=Order.LAB).prefetch_related('results').order_by('-id')[:50]
    prescriptions = Prescription.objects.filter(patient=patient).prefetch_related('items').order_by('-id')[:50]
    invoices = Invoice.objects.filter(patient=patient).order_by('-id')[:50]

    context = {
        'patient': patient,
        'encounters': encounters,
        'lab_orders': lab_orders,
        'prescriptions': prescriptions,
        'invoices': invoices,
    }
    return render(request, 'portal/view.html', context)


@login_required
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
    if patient:
        token = signing.dumps({'p': patient.id}, salt=SALT)
        link = request.build_absolute_uri(reverse('portal-view', args=[token]))

    context = {
        'patient': patient,
        'link': link,
        'max_age_hours': int(MAX_AGE // 3600),
    }
    return render(request, 'portal/token_create.html', context)
