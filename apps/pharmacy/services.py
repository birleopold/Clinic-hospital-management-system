from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from apps.inventory.models import Batch, StockMovement
from apps.demographics.models import Patient
from apps.billing.services import add_line_from_dispense


def usable_batches():
    return Batch.objects.filter(Q(expiry__isnull=True) | Q(expiry__gte=timezone.localdate()), quantity_on_hand__gt=0, quarantined=False).order_by(F('expiry').asc(nulls_last=True), 'pk')


@transaction.atomic
def save_dispense(instance, *args, **kwargs):
    from .models import PrescriptionItem
    if instance.pk:
        raise ValidationError('Dispenses are immutable. Record a correction instead.')
    qty = Decimal(str(instance.quantity))
    if not qty.is_finite() or qty <= 0:
        raise ValidationError('Quantity must be positive.')
    Patient.objects.select_for_update().get(pk=instance.patient_id)
    pi = None
    if instance.prescription_item_id:
        pi = PrescriptionItem.objects.select_for_update().select_related('prescription').get(pk=instance.prescription_item_id)
        if pi.prescription.patient_id != instance.patient_id or pi.item_code != instance.item_code:
            raise ValidationError('Prescription does not match the patient and medicine.')
        if qty > pi.quantity - pi.dispensed_quantity:
            raise ValidationError('Quantity exceeds the outstanding prescription.')
    batches = usable_batches().select_for_update().filter(item__code=instance.item_code, quantity_on_hand__gte=qty)
    if instance.patient.facility_id:
        batches = batches.filter(location__facility_id=instance.patient.facility_id)
    if instance.batch_id:
        batches = batches.filter(pk=instance.batch_id)
    batch = batches.first()
    if not batch:
        raise ValidationError('No unexpired batch has sufficient stock. Choose a smaller quantity.')
    instance.batch = batch
    instance.quantity = qty
    super(type(instance), instance).save(*args, **kwargs)
    Batch.objects.filter(pk=batch.pk).update(quantity_on_hand=F('quantity_on_hand') - qty)
    StockMovement.objects.create(item=batch.item, batch=batch, direction='out', quantity=qty, reason='dispense', ref=f'dispense:{instance.pk}')
    if pi:
        pi.dispensed_quantity += qty
        pi.save(update_fields=['dispensed_quantity'])
    add_line_from_dispense(instance)
