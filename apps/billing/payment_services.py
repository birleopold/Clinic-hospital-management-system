import uuid
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from apps.accounts.models import User
from apps.demographics.models import Patient
from apps.operations.models import Refund, PaymentRequest
from common.facility_scope import filter_by_patient_facility
from .models import Invoice, Payment, CashSession


def money(value, positive=True):
    try:
        value=Decimal(str(value))
        if not value.is_finite() or value<0 or (positive and value==0) or value>Decimal('9999999999.99') or value!=value.quantize(Decimal('.01')):
            raise InvalidOperation
    except (InvalidOperation,ValueError,TypeError):raise ValidationError('Enter a valid amount with at most two decimal places.')
    return value


def net_paid(invoice):
    return (invoice.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0'))-(Refund.objects.filter(payment__invoice=invoice,status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0'))


@transaction.atomic
def collect_cash(invoice_id,actor,amount,key,notes=''):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','cashier')):raise PermissionDenied
    amount=money(amount)
    try:key=uuid.UUID(str(key))
    except (ValueError,TypeError,AttributeError):raise ValidationError('Supply a valid idempotency_key UUID and reuse it when retrying this payment.')
    candidate=filter_by_patient_facility(Invoice.objects.all(),actor).filter(pk=invoice_id).first()
    if not candidate:raise PermissionDenied
    patient=Patient.objects.select_for_update().get(pk=candidate.patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed. Reload before payment.')
    User.objects.select_for_update().get(pk=actor.pk)
    invoice=Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.patient_id!=patient.pk:raise ValidationError('Patient changed. Reload before payment.')
    previous=PaymentRequest.objects.filter(key=key).first()
    if previous:
        if previous.created_by_id!=actor.pk or previous.invoice_id!=invoice.pk or previous.amount!=amount or previous.notes!=notes:
            raise ValidationError('Payment retry key was already used for different payment details.')
        return previous.payment,False
    if invoice.status==Invoice.CANCELLED:raise ValidationError('Cannot pay a cancelled invoice.')
    paid=net_paid(invoice)
    if amount>invoice.total_amount-paid:raise ValidationError('Amount exceeds the outstanding balance.')
    session=CashSession.objects.select_for_update().filter(opened_by=actor,close_time__isnull=True).first()
    if session is None:session=CashSession.objects.create(opened_by=actor)
    payment=Payment(invoice=invoice,cash_session=session,amount=amount,method='cash',notes=notes)
    payment._history_user=actor;payment.save()
    # The unique key also protects competing requests on different cash desks.
    # A collision raises inside this transaction so every money write rolls back.
    PaymentRequest.objects.create(key=key,invoice=invoice,amount=amount,notes=notes,payment=payment,created_by=actor)
    invoice.paid_amount=paid+amount
    invoice.status=Invoice.PAID if invoice.paid_amount>=invoice.total_amount else Invoice.READY
    invoice._history_user=actor;invoice.save(update_fields=['paid_amount','status'])
    session.expected_cash=session.opening_float+(session.payments.filter(method='cash').aggregate(s=Sum('amount'))['s'] or Decimal('0'))-(Refund.objects.filter(cash_session=session,status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0'))
    session._history_user=actor;session.save(update_fields=['expected_cash'])
    return payment,True
