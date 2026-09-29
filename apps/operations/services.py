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

@transaction.atomic
def approve_refund(pk, actor):
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    refund = Refund.objects.select_for_update().get(pk=pk)
    if refund.status == 'approved':
        return refund
    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    previous = payment.refunds.filter(status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    if refund.amount <= 0 or previous + refund.amount > payment.amount:
        raise ValidationError('Refund exceeds the remaining payment amount.')
    session = CashSession.objects.select_for_update().filter(opened_by=actor, close_time__isnull=True).first()
    if not session:
        raise ValidationError('Open your cash session before handing out a cash refund.')
    refund.approved_at = timezone.now()
    refund.status = 'approved'
    refund.approved_by = actor
    refund.cash_session = session
    refund.save()
    invoice.paid_amount -= refund.amount
    invoice.status = Invoice.PAID if invoice.paid_amount >= invoice.total_amount else Invoice.READY
    invoice.save(update_fields=['paid_amount','status'])
    session.expected_cash -= refund.amount
    session.save(update_fields=['expected_cash'])
    return refund

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


@transaction.atomic
def approve_credit(pk, actor):
    from .models import InvoiceCredit
    from apps.billing.models import InvoiceLine
    from apps.billing.services import recalc_invoice
    credit=InvoiceCredit.objects.select_for_update().get(pk=pk)
    if credit.status=='approved': return credit
    invoice=Invoice.objects.select_for_update().get(pk=credit.invoice_id)
    if invoice.status==Invoice.CANCELLED or credit.amount<=0 or credit.amount>invoice.total_amount:
        raise ValidationError('Credit must be positive and within the uncancelled invoice total.')
    InvoiceLine.objects.create(invoice=invoice,code='CREDIT',description=credit.reason,quantity=-1,unit_price=credit.amount,source_ref=f'credit:{credit.pk}')
    recalc_invoice(invoice)
    invoice.status=Invoice.PAID if invoice.paid_amount>=invoice.total_amount else Invoice.READY
    invoice.save(update_fields=['status'])
    credit.status='approved';credit.approved_by=actor;credit.save()
    return credit
