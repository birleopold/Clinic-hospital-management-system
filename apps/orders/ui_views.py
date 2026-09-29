from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseForbidden
from common.facility_scope import filter_by_patient_facility
from .models import Order, OrderResult


def _can_access_worklist(user) -> bool:
    return bool(
        user.is_superuser or getattr(user, 'role', None) in ('admin', 'lab', 'clinician')
    )


@login_required
def lab_worklist_view(request):
    if not _can_access_worklist(request.user):
        return HttpResponseForbidden('Not allowed')
    pending = (
        filter_by_patient_facility(Order.objects.all(), request.user)
        .filter(status=Order.ORDERED)
        .select_related('patient', 'encounter')
        .order_by('created_at', 'id')[:200]
    )
    return render(request, 'orders/worklist.html', {'pending_orders': pending})


@login_required
def lab_submit_result_view(request):
    if not _can_access_worklist(request.user):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    try:
        oid = int(request.POST.get('order_id') or '0')
    except (TypeError, ValueError):
        oid = 0
    order = get_object_or_404(
        filter_by_patient_facility(Order.objects.all(), request.user).select_related('encounter', 'patient'),
        pk=oid,
    )
    if order.status != Order.ORDERED:
        return redirect('labs-worklist')
    text = (request.POST.get('result_text') or '').strip()
    if text:
        OrderResult.objects.create(order=order, result_text=text)
    order.status = Order.COMPLETED
    order.save(update_fields=['status'])
    return redirect('labs-worklist')


def _can_cancel_order(user) -> bool:
    return bool(
        user.is_superuser or getattr(user, 'role', None) in ('admin', 'clinician', 'lab')
    )


@login_required
def cancel_order_ui_view(request, order_id: int):
    if not _can_cancel_order(request.user):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    order = get_object_or_404(
        filter_by_patient_facility(Order.objects.all(), request.user).select_related('encounter'),
        pk=order_id,
    )
    if order.status != Order.ORDERED:
        if order.encounter_id:
            return redirect('ehr-encounter-detail', encounter_id=order.encounter_id)
        return redirect('labs-worklist')
    order.status = Order.CANCELLED
    order.save(update_fields=['status'])
    if order.encounter_id:
        return redirect('ehr-encounter-detail', encounter_id=order.encounter_id)
    return redirect('labs-worklist')
