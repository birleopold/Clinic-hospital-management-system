from apps.accounts.approval_services import require as require_approval
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.accounts.models import User
from apps.demographics.models import Patient
from apps.billing.models import Invoice, InvoiceLine, Payment, CashSession
from apps.billing.payment_services import money, net_paid
from apps.billing.services import recalc_invoice, price_for
from apps.pharmacy.models import Dispense, DispensingBasket, BasketLine
from apps.inventory.models import Batch, StockMovement
from common.facility_scope import filter_by_patient_facility
from .models import (Refund, RefundAuthorization, MedicineReturn, ReturnRefundLink, PriceOverride, InvoiceCredit)


def role(actor, roles):
    if not actor.is_active or not (actor.is_superuser or actor.role in roles):raise PermissionDenied


def supervisor(actor,requester_id):
    role(actor,('admin','manager'))
    if actor.pk==requester_id:raise ValidationError('A different supervisor must review this request.')


def lock_patient(patient_id):
    patient=Patient.objects.select_for_update().get(pk=patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed; reload the canonical record.')
    return patient


def invoice_for(actor,pk):
    invoice=filter_by_patient_facility(Invoice.objects.all(),actor).filter(pk=pk).first()
    if not invoice:raise PermissionDenied
    patient=lock_patient(invoice.patient_id)
    locked=Invoice.objects.select_for_update().get(pk=pk)
    if locked.patient_id!=patient.pk:raise ValidationError('Patient changed. Reload the invoice.')
    return locked


@transaction.atomic
def authorize_refund(pk,actor,reason):
    candidate=Refund.objects.get(pk=pk)
    invoice_for(actor,candidate.payment.invoice_id)
    refund=Refund.objects.select_for_update().get(pk=pk)
    supervisor(actor,refund.created_by_id)
    if not reason.strip():raise ValidationError('Enter an approval reason.')
    if refund.status=='approved':return refund
    if refund.payment.method!='cash':raise ValidationError('Reconcile this refund through the original non-cash provider. No cash substitution is permitted.')
    authorization=RefundAuthorization.objects.filter(refund=refund).first()
    if not authorization or authorization.authorized_amount is None:
        require_approval(actor,refund.payment.invoice.patient.facility_id,'refund',refund.amount)
        if authorization:
            # Retain the original approval; history attributes the revalidation.
            authorization.authorized_amount=refund.amount;authorization.payment_reference=refund.payment_id
            authorization.reason=('Revalidated: '+reason)[:250];authorization._history_user=actor
            authorization.save(update_fields=['authorized_amount','payment_reference','reason'])
        else:
            authorization=RefundAuthorization(refund=refund,created_by=actor,reason=reason,authorized_amount=refund.amount,payment_reference=refund.payment_id)
            authorization._history_user=actor;authorization.save()
    elif authorization.authorized_amount!=refund.amount or authorization.payment_reference!=refund.payment_id:
        raise ValidationError('Refund changed after authorization. Reconcile the original approval before paying.')
    return refund


@transaction.atomic
def disburse_refund(pk,actor,authorize_if_allowed=False):
    role(actor,('admin','cashier','manager'))
    candidate=Refund.objects.get(pk=pk)
    # Keep the patient -> cashier -> invoice lock order used by collection.
    initial=filter_by_patient_facility(Invoice.objects.all(),actor).filter(pk=candidate.payment.invoice_id).first()
    if not initial:raise PermissionDenied
    patient=lock_patient(initial.patient_id)
    User.objects.select_for_update().get(pk=actor.pk)
    invoice=Invoice.objects.select_for_update().get(pk=initial.pk)
    if invoice.patient_id!=patient.pk:raise ValidationError('Patient changed; reload.')
    refund=Refund.objects.select_for_update().get(pk=pk)
    if refund.status=='approved':return refund
    if not RefundAuthorization.objects.filter(refund=refund).exists():
        if not authorize_if_allowed:raise ValidationError('Supervisor authorization is required before paying the refund.')
        authorize_refund(pk,actor,refund.reason)
    authorization=RefundAuthorization.objects.get(refund=refund)
    if authorization.authorized_amount!=refund.amount or authorization.payment_reference!=refund.payment_id:raise ValidationError('Refund changed after authorization. Reconcile the original approval before paying.')
    payment=Payment.objects.select_for_update().get(pk=refund.payment_id)
    if payment.method!='cash':raise ValidationError('Use the original provider for non-cash refunds.')
    previous=payment.refunds.filter(status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    amount=money(refund.amount)
    if previous+amount>payment.amount:raise ValidationError('Refund exceeds the remaining original payment.')
    session=CashSession.objects.select_for_update().filter(opened_by=actor,close_time__isnull=True).first()
    if not session:raise ValidationError('Open your cash session before handing out the refund.')
    refund.status='approved';refund.approved_at=timezone.now();refund.approved_by=actor;refund.cash_session=session
    refund._history_user=actor;refund.save()
    invoice.paid_amount=net_paid(invoice)
    invoice.status=Invoice.PAID if invoice.paid_amount>=invoice.total_amount else Invoice.READY
    invoice._history_user=actor;invoice.save(update_fields=['paid_amount','status'])
    session.expected_cash=session.opening_float+(session.payments.filter(method='cash').aggregate(s=Sum('amount'))['s'] or Decimal('0'))-(Refund.objects.filter(cash_session=session,status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0'))
    session._history_user=actor;session.save(update_fields=['expected_cash'])
    return refund


@transaction.atomic
def approve_invoice_credit(pk,actor):
    candidate=InvoiceCredit.objects.get(pk=pk)
    invoice=invoice_for(actor,candidate.invoice_id)
    credit=InvoiceCredit.objects.select_for_update().get(pk=pk)
    supervisor(actor,credit.created_by_id)
    if credit.status=='approved':return credit
    amount=money(credit.amount)
    if invoice.status==Invoice.CANCELLED or amount>invoice.total_amount:raise ValidationError('Credit exceeds the uncancelled invoice total.')
    require_approval(actor,invoice.patient.facility_id,'credit',amount)
    InvoiceLine.objects.create(invoice=invoice,code='CREDIT',description=credit.reason,quantity=-1,unit_price=amount,source_ref=f'credit:{credit.pk}')
    recalc_invoice(invoice)
    invoice.status=Invoice.PAID if invoice.paid_amount>=invoice.total_amount else Invoice.READY
    invoice.save(update_fields=['status'])
    credit.status='approved';credit.approved_by=actor;credit._history_user=actor;credit.save()
    return credit


@transaction.atomic
def request_return(dispense_id,actor,quantity,disposition,reason,inspection):
    role(actor,('admin','pharmacy'))
    dispense=filter_by_patient_facility(Dispense.objects.all(),actor).filter(pk=dispense_id).first()
    if not dispense:raise PermissionDenied
    patient=lock_patient(dispense.patient_id)
    dispense=Dispense.objects.select_for_update().get(pk=dispense_id)
    if dispense.patient_id!=patient.pk:raise ValidationError('Patient changed; reload.')
    quantity=money(quantity)
    if quantity>dispense.quantity:raise ValidationError('Return exceeds original supplied quantity.')
    if disposition not in ('quarantine','restock','dispose') or not reason.strip() or not inspection.strip():raise ValidationError('Record a disposition, reason and inspection evidence.')
    obj=MedicineReturn(dispense=dispense,quantity=quantity,disposition=disposition,reason=reason,inspection=inspection,created_by=actor)
    obj.full_clean(exclude=['reviewed_by','reviewed_at','credit_line','returned_batch'])
    obj._history_user=actor;obj.save();return obj


@transaction.atomic
def review_return(pk,actor,decision,reason):
    candidate=MedicineReturn.objects.select_related('dispense').get(pk=pk)
    original=InvoiceLine.objects.filter(source_ref=f'dispense:{candidate.dispense_id}').first()
    if not original:raise ValidationError('Original dispense invoice line is missing; reconcile before returning.')
    invoice=invoice_for(actor,original.invoice_id)
    obj=MedicineReturn.objects.select_for_update().get(pk=pk)
    supervisor(actor,obj.created_by_id)
    if obj.status!='requested':return obj
    if not reason.strip() or decision not in ('post','reject'):raise ValidationError('Choose a decision and enter a review reason.')
    if decision=='reject':
        obj.status='rejected'
    else:
        if invoice.status==Invoice.CANCELLED:raise ValidationError('Reconcile the cancelled invoice first.')
        dispense=Dispense.objects.select_for_update().get(pk=obj.dispense_id)
        prior=MedicineReturn.objects.filter(dispense=dispense,status='posted').aggregate(q=Sum('quantity'),a=Sum('amount'))
        previous_qty=prior['q'] or Decimal('0');previous_amount=prior['a'] or Decimal('0')
        if obj.quantity+previous_qty>dispense.quantity:raise ValidationError('Already returned quantities leave insufficient quantity for this request.')
        amount=(obj.quantity*original.unit_price).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if obj.quantity+previous_qty==dispense.quantity:amount=original.line_total-previous_amount
        amount=min(amount,original.line_total-previous_amount)
        if amount<0 or amount>invoice.total_amount:raise ValidationError('Prior credits require manual reconciliation before this return.')
        require_approval(actor,invoice.patient.facility_id,'return',amount)
        batch=Batch.objects.select_for_update().filter(pk=dispense.batch_id).first()
        if not batch or not batch.location_id or batch.location.facility_id!=dispense.patient.facility_id:raise ValidationError('Original batch and facility location must be reconciled first.')
        if obj.disposition=='restock' and (batch.quarantined or (batch.expiry and batch.expiry<timezone.localdate())):
            raise ValidationError('Expired or quarantined medicine cannot return to usable stock.')
        returned=Batch.objects.create(item=batch.item,location=batch.location,batch_no=batch.batch_no,expiry=batch.expiry,quantity_on_hand=0 if obj.disposition=='dispose' else obj.quantity,quarantined=obj.disposition!='restock')
        StockMovement.objects.create(item=batch.item,batch=returned,direction='in',quantity=obj.quantity,reason='patient return',ref=f'return:{obj.pk}')
        if obj.disposition=='dispose':StockMovement.objects.create(item=batch.item,batch=returned,direction='out',quantity=obj.quantity,reason='return disposal',ref=f'return:{obj.pk}')
        obj.returned_batch=returned;obj.amount=amount
        obj.credit_line=InvoiceLine.objects.create(invoice=invoice,code=original.code,description=f'Return #{obj.pk}: {obj.reason}'[:255],quantity=-1,unit_price=amount,source_ref=f'return:{obj.pk}')
        recalc_invoice(invoice);invoice.paid_amount=net_paid(invoice)
        invoice.status=Invoice.PAID if invoice.paid_amount>=invoice.total_amount else Invoice.READY
        invoice.save(update_fields=['paid_amount','status'])
        # Reserve requested refund amounts across original payments. Only the
        # overpaid part is returned; unpaid returns reduce the balance instead.
        pending=Refund.objects.filter(payment__invoice=invoice,status='requested').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        owed=max(Decimal('0'),invoice.paid_amount-invoice.total_amount-pending)
        for payment in invoice.payments.order_by('pk'):
            reserved=payment.refunds.aggregate(s=Sum('amount'))['s'] or Decimal('0')
            value=min(owed,max(Decimal('0'),payment.amount-reserved))
            if value:
                refund=Refund.objects.create(payment=payment,amount=value,reason=f'Medicine return #{obj.pk}',created_by=obj.created_by)
                ReturnRefundLink.objects.create(medicine_return=obj,refund=refund)
                # Return review authorizes cash refund, but never records handout.
                if payment.method=='cash':
                    require_approval(actor,invoice.patient.facility_id,'refund',value)
                    RefundAuthorization.objects.create(refund=refund,created_by=actor,reason=reason,authorized_amount=refund.amount,payment_reference=refund.payment_id)
                owed-=value
            if not owed:break
        obj.status='posted'
    obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason
    obj._history_user=actor;obj.save();return obj


@transaction.atomic
def request_price(line_id,actor,requested_price,reason):
    role(actor,('admin','pharmacy'))
    initial=filter_by_patient_facility(BasketLine.objects.all(),actor,prefix='basket__patient__').filter(pk=line_id).first()
    if not initial:raise PermissionDenied
    lock_patient(initial.basket.patient_id)
    basket=DispensingBasket.objects.select_for_update().get(pk=initial.basket_id)
    line=BasketLine.objects.get(pk=line_id)
    if basket.status!='open' or line.removed:raise ValidationError('Only active lines of an open basket can be repriced.')
    if not reason.strip():raise ValidationError('Enter a price exception reason.')
    if PriceOverride.objects.filter(line=line,status__in=['requested','approved']).exists():raise ValidationError('This line already has an active price review. Remove/re-add it for a new price.')
    obj=PriceOverride.objects.create(line=line,catalog_price=line.unit_price,requested_price=money(requested_price,positive=False),reason=reason,created_by=actor)
    from apps.pharmacy.checkout_services import save_basket
    save_basket(basket,actor);return obj


@transaction.atomic
def review_price(pk,actor,decision,reason):
    initial=PriceOverride.objects.select_related('line__basket').get(pk=pk)
    invoice_patient=initial.line.basket.patient_id
    if not filter_by_patient_facility(DispensingBasket.objects.all(),actor).filter(pk=initial.line.basket_id).exists():raise PermissionDenied
    lock_patient(invoice_patient)
    basket=DispensingBasket.objects.select_for_update().get(pk=initial.line.basket_id)
    obj=PriceOverride.objects.select_for_update().get(pk=pk)
    supervisor(actor,obj.created_by_id)
    if obj.status!='requested':return obj
    if not reason.strip() or decision not in ('approve','reject'):raise ValidationError('Enter a decision and review reason.')
    line=BasketLine.objects.select_for_update().get(pk=obj.line_id)
    if basket.status!='open' or line.removed:raise ValidationError('Basket changed. Reopen and review its current lines.')
    if decision=='approve':
        require_approval(actor,basket.patient.facility_id,'price',(abs(obj.requested_price-obj.catalog_price)*line.quantity).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        if price_for(line.item.code)!=obj.catalog_price or line.unit_price!=obj.catalog_price:raise ValidationError('Catalog price changed; reject and replace this line.')
        line.unit_price=obj.requested_price;line._history_user=actor;line.save(update_fields=['unit_price'])
        obj.status='approved'
    else:obj.status='rejected'
    obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason;obj._history_user=actor;obj.save()
    from apps.pharmacy.checkout_services import save_basket
    save_basket(basket,actor);return obj
