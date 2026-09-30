"""Reviewed, retry-safe expense disbursement evidence. No gateway is called."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import OperatingExpense, ExpenseSettlement
from .workforce_services import manager, facility_lock, reason_required
from .finance_services import supervisor


@transaction.atomic
def record_settlement(actor, expense_id, **data):
    manager(actor)
    expense = OperatingExpense.objects.select_related('budget').get(pk=expense_id)
    facility_lock(actor, expense.budget.facility_id)
    expense = OperatingExpense.objects.select_for_update().get(pk=expense_id)
    fields = ('amount', 'paid_on', 'method', 'account_reference', 'transaction_reference', 'evidence')
    previous = ExpenseSettlement.objects.filter(request_key=data['request_key']).first()
    if previous:
        if previous.expense_id != expense_id or any(getattr(previous, key) != data[key] for key in fields):
            raise ValidationError('Settlement reference conflict. Reload and review the original record.')
        return previous
    if expense.status != 'approved':
        raise ValidationError('Approve the expense before recording a settlement.')
    amount = Decimal(data['amount'])
    if not amount.is_finite() or amount <= 0:
        raise ValidationError('Record a positive, finite amount.')
    if data['paid_on'] > timezone.localdate() or data['paid_on'] < expense.incurred_on:
        raise ValidationError('Payment date must be between the expense date and today.')
    for key in ('account_reference', 'transaction_reference', 'evidence'):
        if not data[key].strip():
            raise ValidationError('Account, transaction reference and supporting evidence are required.')
    # A facility lock serializes cross-expense reference checks, including concurrent requests.
    if ExpenseSettlement.objects.filter(expense__budget__facility_id=expense.budget.facility_id, method=data['method'], account_reference=data['account_reference'], transaction_reference=data['transaction_reference']).exists():
        raise ValidationError('This account transaction is already recorded. Reconcile the existing record.')
    reserved = expense.settlements.exclude(status='rejected').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    if reserved + amount > expense.amount:
        raise ValidationError('Settlement exceeds the approved outstanding amount, including pending evidence.')
    obj = ExpenseSettlement(expense=expense, created_by=actor, **data)
    obj.full_clean(); obj.save()
    return obj


@transaction.atomic
def reconcile(actor, pk, decision, reason):
    manager(actor)
    candidate = ExpenseSettlement.objects.select_related('expense__budget').get(pk=pk)
    facility_lock(actor, candidate.expense.budget.facility_id)
    OperatingExpense.objects.select_for_update().get(pk=candidate.expense_id)
    obj = ExpenseSettlement.objects.select_for_update().get(pk=pk)
    supervisor(actor, obj.created_by_id)
    reason_required(reason)
    if decision not in ('confirmed', 'rejected'):
        raise ValidationError('Choose reconcile or reject evidence.')
    if obj.status != 'pending':
        if obj.status != decision:
            raise ValidationError('A reconciled decision is immutable. Preserve this evidence and arrange an accounting correction with your supervisor.')
        return obj
    obj.status = decision; obj.reconciled_by = actor; obj.reconciled_at = timezone.now(); obj.review_reason = reason
    obj._history_user = actor; obj.save()
    return obj
