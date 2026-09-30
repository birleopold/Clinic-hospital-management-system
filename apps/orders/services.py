"""Order cancellation shares the patient/order lock order used by diagnostics."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from common.facility_scope import filter_by_patient_facility
from apps.demographics.models import Patient
from .models import Order


@transaction.atomic
def cancel_order(pk,actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','clinician','lab')):raise PermissionDenied
    candidate=filter_by_patient_facility(Order.objects.all(),actor).filter(pk=pk).first()
    if not candidate:raise PermissionDenied
    patient=Patient.objects.select_for_update().get(pk=candidate.patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed; reload.')
    order=Order.objects.select_for_update().get(pk=pk)
    if order.patient_id!=patient.pk:raise ValidationError('Patient identity changed; reload.')
    if order.status==Order.CANCELLED:return order
    if order.status!=Order.ORDERED or order.results.filter(approved_at__isnull=False).exists():raise ValidationError('A completed or released order cannot be cancelled.')
    order.status=Order.CANCELLED;order._history_user=actor;order.save(update_fields=['status']);return order
