from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.db.models import Sum
from datetime import date, timedelta

from .models import Dispense, Prescription, PrescriptionItem
from apps.inventory.models import InventoryItem, Batch
from apps.demographics.models import Patient
from apps.billing.models import ClinicConfig
from common.exports import pdf_response_from_template
from common.facility_scope import filter_by_patient_facility
from .models import Backorder


@login_required
def pharmacy_board_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    prescriptions = (
        filter_by_patient_facility(Prescription.objects.all(), user)
        .select_related('patient','clinician')
        .prefetch_related('items')
        .order_by('-id')[:30]
    )
    recent_dispenses = (
        filter_by_patient_facility(Dispense.objects.all(), user)
        .select_related('patient')
        .order_by('-dispensed_at')[:30]
    )
    # FEFO batches per item_code for quick selection
    item_codes = set()
    for rx in prescriptions:
        for it in rx.items.all():
            if it.item_code:
                item_codes.add(it.item_code)
    code_to_item = {i.code: i.id for i in InventoryItem.objects.filter(code__in=item_codes)}
    batches_map = {}
    avail_map = {}
    if code_to_item:
        batches = (
            Batch.objects
            .filter(item_id__in=code_to_item.values(), quantity_on_hand__gt=0)
            .order_by('expiry','id')
        )
        # Group by code
        from collections import defaultdict
        tmp = defaultdict(list)
        cfg = ClinicConfig.get_solo()
        near_cutoff = date.today() + timedelta(days=getattr(cfg, 'near_expiry_days', 30))
        for b in batches:
            # reverse map item id to code
            for code, iid in code_to_item.items():
                if iid == b.item_id:
                    # mark near expiry for UI warning
                    try:
                        setattr(b, 'near_expiry', bool(b.expiry and b.expiry <= near_cutoff))
                    except Exception:
                        setattr(b, 'near_expiry', False)
                    tmp[code].append(b)
                    break
        for code, arr in tmp.items():
            batches_map[code] = arr[:8]
        # availability totals
        totals = (
            Batch.objects
            .filter(item_id__in=code_to_item.values())
            .values('item_id').annotate(total=Sum('quantity_on_hand'))
        )
        iid_to_total = {row['item_id']: row['total'] for row in totals}
        for code, iid in code_to_item.items():
            avail_map[code] = iid_to_total.get(iid, 0)
    # attach per-item helpers for templates
    for rx in prescriptions:
        for it in rx.items.all():
            code = it.item_code
            setattr(it, 'avail_total', avail_map.get(code, 0))
            setattr(it, 'fefo_batches', batches_map.get(code, []))
    context = {
        'prescriptions': prescriptions,
        'recent_dispenses': recent_dispenses,
    }
    return render(request, 'pharmacy/board.html', context)


@login_required
def dispense_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')

    # Determine patient and item context
    try:
        prescription_item_id = int(request.POST.get('prescription_item_id') or '0')
    except Exception:
        prescription_item_id = 0
    item_code = (request.POST.get('item_code') or '').strip()
    try:
        quantity = Decimal(request.POST.get('quantity') or '0')
    except Exception:
        quantity = Decimal('0')
    try:
        batch_id = int(request.POST.get('batch_id') or '0')
    except Exception:
        batch_id = 0

    patient = None
    pi = None
    if prescription_item_id:
        pi = get_object_or_404(PrescriptionItem.objects.select_related('prescription__patient'), pk=prescription_item_id)
        patient = pi.prescription.patient
        if not item_code:
            item_code = pi.item_code
    else:
        try:
            patient_id = int(request.POST.get('patient_id') or '0')
        except Exception:
            patient_id = 0
        if patient_id:
            patient = get_object_or_404(Patient, pk=patient_id)

    # Basic validations
    if not patient:
        return HttpResponseForbidden('Missing patient')
    if not item_code:
        return HttpResponseForbidden('Missing item code')
    if quantity <= 0:
        return HttpResponseForbidden('Quantity must be > 0')

    # Stock check
    try:
        item = InventoryItem.objects.get(code=item_code)
    except InventoryItem.DoesNotExist:
        # optional create-on-the-fly if requested
        create_flag = (request.POST.get('create_if_missing') == '1')
        if not create_flag:
            return HttpResponseForbidden('Unknown inventory item code')
        name_guess = (request.POST.get('item_name') or (pi.item_name if pi else '') or item_code).strip()
        item = InventoryItem.objects.create(code=item_code, name=name_guess)
    available = Batch.objects.filter(item=item).aggregate(total=Sum('quantity_on_hand'))['total'] or 0
    if quantity > available:
        # Auto-create backorder and stop
        bo = Backorder.objects.create(
            patient=patient,
            prescription_item=pi,
            item_code=item_code,
            item_name=getattr(item, 'name', ''),
            quantity=quantity - (available or 0),
        )
        return HttpResponseForbidden(f'Insufficient stock. Backorder created #{bo.id} for shortage {bo.quantity}. Available now: {available}.')

    # Determine batch for this dispense
    selected_batch = None
    if batch_id:
        try:
            b = Batch.objects.get(pk=batch_id)
        except Batch.DoesNotExist:
            return HttpResponseForbidden('Invalid batch selected')
        if b.item_id != item.id:
            return HttpResponseForbidden('Selected batch does not match item')
        if (b.quantity_on_hand or 0) < quantity:
            return HttpResponseForbidden(f'Selected batch has insufficient stock ({b.quantity_on_hand}). Choose a different batch or lower qty.')
        selected_batch = b
    else:
        # FEFO single-batch selection (must have enough in one batch)
        selected_batch = (
            Batch.objects
            .filter(item=item, quantity_on_hand__gte=quantity)
            .order_by('expiry','id')
            .first()
        )
        if not selected_batch:
            return HttpResponseForbidden('Insufficient in a single batch. Please select a batch and adjust quantity.')

    # Create dispense
    disp = Dispense.objects.create(
        patient=patient,
        prescription_item=pi,
        batch=selected_batch,
        item_code=item_code,
        item_name=getattr(item, 'name', ''),
        quantity=quantity,
        notes=(request.POST.get('notes') or ''),
    )

    # Update dispensed qty on prescription item if linked
    if pi:
        new_disp = (pi.dispensed_quantity or 0) + quantity
        PrescriptionItem.objects.filter(pk=pi.pk).update(dispensed_quantity=new_disp)

    return redirect('pharmacy-board')


@login_required
def rx_detail_view(request, rx_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','clinician','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    rx = get_object_or_404(
        filter_by_patient_facility(Prescription.objects.all(), user).select_related('patient','clinician').prefetch_related('items'),
        pk=rx_id,
    )
    context = {
        'rx': rx,
        'items': rx.items.all().order_by('id'),
    }
    return render(request, 'pharmacy/rx_detail.html', context)


@login_required
def rx_item_add_view(request, rx_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    rx = get_object_or_404(Prescription, pk=rx_id)
    item_code = (request.POST.get('item_code') or '').strip()
    item_name = (request.POST.get('item_name') or '').strip()
    dose = (request.POST.get('dose') or '').strip()
    frequency = (request.POST.get('frequency') or '').strip()
    duration = (request.POST.get('duration') or '').strip()
    try:
        quantity = Decimal(request.POST.get('quantity') or '1')
    except Exception:
        quantity = Decimal('1')
    if not item_code:
        return redirect('rx-detail', rx_id=rx.id)
    PrescriptionItem.objects.create(
        prescription=rx,
        item_code=item_code,
        item_name=item_name,
        dose=dose,
        frequency=frequency,
        duration=duration,
        quantity=quantity,
    )
    return redirect('rx-detail', rx_id=rx.id)


@login_required
def rx_item_delete_view(request, item_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','clinician')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    it = get_object_or_404(PrescriptionItem, pk=item_id)
    rx_id = it.prescription_id
    it.delete()
    return redirect('rx-detail', rx_id=rx_id)


@login_required
def dispense_print_view(request, dispense_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy','cashier')):
        return HttpResponseForbidden('Not allowed')
    disp = get_object_or_404(
        filter_by_patient_facility(Dispense.objects.all(), user).select_related('patient'),
        pk=dispense_id,
    )
    cfg = ClinicConfig.get_solo()
    template = 'pharmacy/dispense_a4.html' if cfg.receipt_paper == ClinicConfig.A4 else 'pharmacy/dispense_80mm.html'
    ctx = {
        'config': cfg,
        'dispense': disp,
    }
    if request.GET.get('format') == 'pdf':
        return pdf_response_from_template(template, ctx, f'dispense_{dispense_id}.pdf')
    return render(request, template, ctx)


# Backorders UI
@login_required
def backorders_list_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    status_f = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()
    qs = Backorder.objects.select_related('patient').order_by('-created_at')
    if status_f:
        qs = qs.filter(status=status_f)
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(item_code__icontains=q) | Q(item_name__icontains=q) |
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q)
        )
    return render(request, 'pharmacy/backorders_list.html', {'backorders': qs[:300], 'status': status_f, 'q': q})


@login_required
def backorder_detail_view(request, bo_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    bo = get_object_or_404(Backorder.objects.select_related('patient','prescription_item'), pk=bo_id)
    # Gather FEFO batches and availability for this item code
    it = InventoryItem.objects.filter(code=bo.item_code).first()
    fefo_batches = []
    avail_total = 0
    if it:
        cfg = ClinicConfig.get_solo()
        near_cutoff = date.today() + timedelta(days=getattr(cfg, 'near_expiry_days', 30))
        fefo_batches = list(Batch.objects.filter(item=it, quantity_on_hand__gt=0).order_by('expiry','id')[:12])
        for b in fefo_batches:
            try:
                setattr(b, 'near_expiry', bool(b.expiry and b.expiry <= near_cutoff))
            except Exception:
                setattr(b, 'near_expiry', False)
        avail_total = Batch.objects.filter(item=it).aggregate(total=Sum('quantity_on_hand'))['total'] or 0
    ctx = {
        'bo': bo,
        'item': it,
        'fefo_batches': fefo_batches,
        'avail_total': avail_total,
    }
    return render(request, 'pharmacy/backorder_detail.html', ctx)


@login_required
def backorder_fulfill_view(request, bo_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    bo = get_object_or_404(Backorder.objects.select_related('patient','prescription_item'), pk=bo_id)
    try:
        qty = Decimal(request.POST.get('quantity') or '0')
    except Exception:
        qty = Decimal('0')
    try:
        batch_id = int(request.POST.get('batch_id') or '0')
    except Exception:
        batch_id = 0
    if qty <= 0:
        return HttpResponseForbidden('Quantity must be > 0')
    # Resolve or create item
    item = InventoryItem.objects.filter(code=bo.item_code).first()
    if not item:
        if request.POST.get('create_if_missing') == '1':
            name_guess = (request.POST.get('item_name') or bo.item_name or bo.item_code).strip()
            item = InventoryItem.objects.create(code=bo.item_code, name=name_guess)
        else:
            return HttpResponseForbidden('Inventory item not found for this backorder')
    available = Batch.objects.filter(item=item).aggregate(total=Sum('quantity_on_hand'))['total'] or 0
    if qty > available:
        return HttpResponseForbidden(f'Insufficient stock. Available: {available}.')
    # Select batch: require single batch to cover the qty
    selected_batch = None
    if batch_id:
        b = get_object_or_404(Batch, pk=batch_id)
        if b.item_id != item.id:
            return HttpResponseForbidden('Selected batch does not match item')
        if (b.quantity_on_hand or 0) < qty:
            return HttpResponseForbidden(f'Selected batch has only {b.quantity_on_hand} available')
        selected_batch = b
    else:
        selected_batch = (
            Batch.objects
            .filter(item=item, quantity_on_hand__gte=qty)
            .order_by('expiry','id')
            .first()
        )
        if not selected_batch:
            return HttpResponseForbidden('Insufficient in a single batch. Choose a batch or lower quantity.')
    # Create dispense
    Dispense.objects.create(
        patient=bo.patient,
        prescription_item=bo.prescription_item,
        batch=selected_batch,
        item_code=bo.item_code,
        item_name=(bo.item_name or item.name),
        quantity=qty,
        notes=f'Manual fulfill BO#{bo.id}',
    )
    # Update BO progress
    bo.fulfilled_quantity = (bo.fulfilled_quantity or Decimal('0')) + qty
    if bo.fulfilled_quantity >= (bo.quantity or Decimal('0')):
        bo.status = Backorder.CLOSED
    bo.save(update_fields=['fulfilled_quantity','status'])
    return redirect('pharmacy-backorder-detail', bo_id=bo.id)


@login_required
def backorder_close_view(request, bo_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    bo = get_object_or_404(Backorder, pk=bo_id)
    bo.status = Backorder.CLOSED
    bo.save(update_fields=['status'])
    return redirect('pharmacy-backorder-detail', bo_id=bo.id)
