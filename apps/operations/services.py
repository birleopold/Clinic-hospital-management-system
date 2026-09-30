from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import StockCount, Refund, Admission
from apps.inventory.models import Batch, StockMovement
from apps.billing.models import Payment, Invoice, CashSession

@transaction.atomic
def post_count(pk, actor):
    count = StockCount.objects.select_for_update().get(pk=pk)
    if count.status == 'posted':
        return count
    if count.created_by_id == actor.pk and not actor.is_superuser:
        raise ValidationError('A different supervisor must approve this stock count.')
    batch = Batch.objects.select_for_update().get(pk=count.batch_id)
    if batch.quantity_on_hand != count.expected:
        raise ValidationError('Stock moved since counting. Start a fresh count.')
    delta = count.counted - batch.quantity_on_hand
    if delta:
        StockMovement.objects.create(item=batch.item, batch=batch, direction='adjust', quantity=delta, reason=count.reason[:64], ref=f'count:{count.pk}')
    batch.quantity_on_hand = count.counted
    batch.save(update_fields=['quantity_on_hand'])
    count.status = 'posted'
    count.approved_by = actor
    count.save()
    return count

def approve_refund(pk, actor):
    from .finance_services import disburse_refund
    return disburse_refund(pk,actor,authorize_if_allowed=True)

@transaction.atomic
def transfer_stock(batch_id, destination, quantity, actor):
    source = Batch.objects.select_for_update().get(pk=batch_id)
    quantity = Decimal(str(quantity))
    if not quantity.is_finite() or quantity <= 0 or quantity > source.quantity_on_hand:
        raise ValidationError('Transfer quantity must be positive and available.')
    if not source.location_id or source.location.facility_id != destination.facility_id:
        raise ValidationError('Transfers require locations in the same facility.')
    if source.location_id == destination.pk:
        raise ValidationError('Choose a different destination.')
    target = Batch.objects.create(item=source.item, batch_no=source.batch_no, expiry=source.expiry, quantity_on_hand=quantity, location=destination, quarantined=source.quarantined)
    source.quantity_on_hand -= quantity
    source.save(update_fields=['quantity_on_hand'])
    ref = f'transfer:{source.pk}:{target.pk}:user:{actor.pk}'
    for batch, direction in [(source,'out'),(target,'in')]:
        StockMovement.objects.create(item=source.item, batch=batch, direction=direction, quantity=quantity, reason='transfer', ref=ref)
    return target


def approve_credit(pk, actor):
    from .finance_services import approve_invoice_credit
    return approve_invoice_credit(pk,actor)
