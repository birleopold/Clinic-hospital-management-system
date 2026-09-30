from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.urls import reverse

from .models import Encounter, Vital, Diagnosis
from apps.demographics.models import Patient
from apps.pharmacy.models import Prescription
from apps.orders.models import Order
from apps.billing.models import InvoiceLine
from common.facility_scope import filter_by_facility


def _encounters_for_user(user):
    return filter_by_facility(Encounter.objects.all(), user)


@login_required
def ehr_board_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'nurse', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    base = _encounters_for_user(user).select_related('patient', 'clinician')
    if request.GET.get('patient','').isdigit():base=base.filter(patient_id=int(request.GET['patient']))
    open_encounters = (
        base.filter(status=Encounter.OPEN)
        .order_by('-started_at')[:100]
    )
    recent_closed = (
        base.filter(status=Encounter.CLOSED)
        .order_by('-ended_at')[:20]
    )
    context = {
        'open_encounters': open_encounters,
        'recent_closed': recent_closed,
        'error': request.GET.get('err') or '',
    }
    return render(request, 'encounters/board.html', context)


@login_required
def start_encounter_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'nurse', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    try:
        patient_id = int(request.POST.get('patient_id') or '0')
    except Exception:
        patient_id = 0
    # Fallback: if user typed but didn't pick from autocomplete, try to parse an ID like "#123"
    if not patient_id:
        text = (request.POST.get('patient_search') or request.POST.get('patient') or '').strip()
        if text:
            cleaned = text.replace('#', ' ').strip()
            for tok in cleaned.split():
                if tok.isdigit():
                    try:
                        patient_id = int(tok)
                        break
                    except Exception:
                        pass
    patient = filter_by_facility(Patient.objects.all(), user).filter(pk=patient_id).first()
    if not patient:
        return redirect(f"{reverse('ehr-board')}?err=Select a patient from the suggestions before starting.")
    chief = (request.POST.get('chief_complaint') or '').strip()[:255]
    enc = Encounter.objects.create(patient=patient, clinician=user, chief_complaint=chief)
    return redirect('ehr-encounter-detail', encounter_id=enc.id)


@login_required
def encounter_detail_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'nurse', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    enc = get_object_or_404(
        _encounters_for_user(user).select_related('patient', 'clinician'),
        pk=encounter_id,
    )
    from common.service_policy import enabled
    rx_list = Prescription.objects.filter(encounter=enc).prefetch_related('items').order_by('-id')
    visit_orders = (
        Order.objects.filter(encounter=enc)
        .prefetch_related('results')
        .order_by('-created_at', '-id')
    )
    if not enabled(user,'lab'):visit_orders=visit_orders.exclude(order_type='lab')
    if not enabled(user,'imaging'):visit_orders=visit_orders.exclude(order_type='imaging')
    visit_orders=visit_orders[:50]
    # Map each order to its invoice (if auto-billed)
    order_refs = [f"order:{o.id}" for o in visit_orders]
    lines = InvoiceLine.objects.filter(source_ref__in=order_refs).select_related('invoice')
    invoice_by_order = {}
    for ln in lines:
        try:
            oid = int((ln.source_ref or '').split(':', 1)[1])
            invoice_by_order[oid] = ln.invoice_id
        except Exception:
            continue
    # attach invoice_id onto order objects for template ease
    for o in visit_orders:
        o.invoice_id = invoice_by_order.get(o.id)
    context = {
        'encounter': enc,
        'vitals': enc.vitals.all().order_by('-taken_at')[:50],
        'diagnoses': enc.diagnoses.all().order_by('-id')[:50],
        'rx_list': rx_list,
        'visit_orders': visit_orders,
        'invoice_by_order': invoice_by_order,
    }
    return render(request, 'encounters/detail.html', context)


@login_required
def add_vital_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'nurse')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    enc = get_object_or_404(_encounters_for_user(user), pk=encounter_id)
    def dec(name):
        val = request.POST.get(name)
        try:
            return Decimal(val) if val not in (None, '') else None
        except Exception:
            return None
    def pint(name):
        val = request.POST.get(name)
        try:
            return int(val) if val not in (None, '') else None
        except Exception:
            return None
    Vital.objects.create(
        encounter=enc,
        temperature_c=dec('temperature_c'),
        pulse=pint('pulse'),
        systolic=pint('systolic'),
        diastolic=pint('diastolic'),
        respiratory_rate=pint('respiratory_rate'),
        spo2=pint('spo2'),
        weight_kg=dec('weight_kg'),
        height_cm=dec('height_cm'),
    )
    return redirect('ehr-encounter-detail', encounter_id=enc.id)


@login_required
def add_diagnosis_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    enc = get_object_or_404(_encounters_for_user(user), pk=encounter_id)
    code = (request.POST.get('code') or '').strip()
    coding_system = (request.POST.get('coding_system') or Diagnosis.ICD10).strip()[:16]
    if coding_system not in dict(Diagnosis.CODING_SYSTEM_CHOICES):
        coding_system = Diagnosis.ICD10
    description = (request.POST.get('description') or '').strip()
    is_primary = (request.POST.get('is_primary') or '').strip().lower() in ('1', 'true', 'on', 'yes')
    if code:
        Diagnosis.objects.create(
            encounter=enc,
            code=code,
            coding_system=coding_system,
            description=description,
            is_primary=is_primary,
        )
    return redirect('ehr-encounter-detail', encounter_id=enc.id)


@login_required
def close_encounter_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    enc = get_object_or_404(_encounters_for_user(user), pk=encounter_id)
    enc.status = Encounter.CLOSED
    enc.ended_at = timezone.now()
    enc.save(update_fields=['status', 'ended_at'])
    return redirect('ehr-board')


@login_required
def create_rx_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    enc = get_object_or_404(_encounters_for_user(user).select_related('patient'), pk=encounter_id)
    Prescription.objects.create(patient=enc.patient, clinician=user, encounter=enc)
    return redirect('ehr-encounter-detail', encounter_id=enc.id)


@login_required
def create_lab_order_view(request, encounter_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin', 'clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    enc = get_object_or_404(_encounters_for_user(user).select_related('patient'), pk=encounter_id)
    if enc.status != Encounter.OPEN:
        return redirect('ehr-encounter-detail', encounter_id=enc.id)
    code = (request.POST.get('code') or '').strip()
    if not code:
        return redirect('ehr-encounter-detail', encounter_id=enc.id)
    description = (request.POST.get('description') or '').strip()
    order_type = (request.POST.get('order_type') or Order.LAB).strip()
    if order_type not in (Order.LAB, Order.IMAGING, Order.PROCEDURE):
        order_type = Order.LAB
    from common.service_policy import enabled
    if not enabled(user,'clinical' if order_type=='procedure' else order_type):return HttpResponseForbidden('This service is disabled.')
    qty_raw = (request.POST.get('quantity') or '1').strip()
    try:
        quantity = Decimal(qty_raw)
        if quantity <= 0:
            quantity = Decimal('1')
    except (InvalidOperation, TypeError):
        quantity = Decimal('1')
    billable = (request.POST.get('billable') or '').strip().lower() not in ('0', 'false', 'off', 'no')
    if not enabled(user,'billing'):billable=False
    Order.objects.create(
        patient=enc.patient,
        encounter=enc,
        order_type=order_type,
        code=code,
        description=description,
        quantity=quantity,
        billable=billable,
    )
    return redirect('ehr-encounter-detail', encounter_id=enc.id)
