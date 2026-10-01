from apps.accounts.approval_services import require as require_approval
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .workforce_services import facility_lock, manager, staff_at, reason_required
from .finance_services import supervisor
from .models import ManagementCase, CorrectiveAction, FacilityAsset, AssetEvent, StaffChecklist, OperatingBudget, OperatingExpense


@transaction.atomic
def create_record(actor,form):
    obj=form.save(commit=False)
    if isinstance(obj,OperatingExpense):facility_id=obj.budget.facility_id
    elif isinstance(obj,CorrectiveAction):facility_id=obj.case.facility_id
    elif isinstance(obj,AssetEvent):facility_id=obj.asset.facility_id
    else:facility_id=obj.facility_id
    manager(actor);facility_lock(actor,facility_id)
    for field in ('owner','custodian','staff'):
        user=getattr(obj,field,None)
        if user:staff_at(user,facility_id)
    if isinstance(obj,ManagementCase):
        if obj.owner.role not in ('admin','manager') and not obj.owner.is_superuser:raise ValidationError('Restricted cases require a manager owner.')
    elif isinstance(obj,CorrectiveAction):
        case=ManagementCase.objects.select_for_update().get(pk=obj.case_id)
        if case.status!='open':raise ValidationError('Reopen the case before adding corrective actions.')
        if obj.owner.role not in ('admin','manager') and not obj.owner.is_superuser:raise ValidationError('Restricted corrective actions require a manager owner.')
    elif isinstance(obj,StaffChecklist):
        if obj.kind in ('training','policy') and not obj.version.strip():raise ValidationError('Record the policy or training version.')
    elif isinstance(obj,OperatingBudget):
        if obj.ends_on<obj.starts_on:raise ValidationError('Budget end must be on or after start.')
    elif isinstance(obj,OperatingExpense):
        budget=OperatingBudget.objects.select_for_update().get(pk=obj.budget_id)
        if budget.status!='approved' or not budget.starts_on<=obj.incurred_on<=budget.ends_on:raise ValidationError('Expense must fall within an approved budget period.')
        if not obj.reference.strip():raise ValidationError('A supporting document reference is required.')
        if OperatingExpense.objects.filter(budget__facility_id=facility_id,payee__iexact=obj.payee.strip(),reference__iexact=obj.reference.strip()).exclude(status='rejected').exists():raise ValidationError('This supplier invoice is already recorded in the facility expense register.')
        obj.payee=obj.payee.strip();obj.reference=obj.reference.strip()
    elif isinstance(obj,AssetEvent):
        asset=FacilityAsset.objects.select_for_update().get(pk=obj.asset_id)
        if asset.status=='retired':raise ValidationError('Retired assets cannot receive new service events.')
        if obj.kind in ('maintenance','calibration'):
            if not obj.next_due or obj.next_due<=timezone.localdate():raise ValidationError('Record the next service due date.')
            setattr(asset,'maintenance_due' if obj.kind=='maintenance' else 'calibration_due',obj.next_due)
        elif obj.kind=='downtime':asset.status='out_of_service'
        elif obj.kind=='restore':asset.status='operational'
        elif obj.kind=='retire':asset.status='retired'
        asset._history_user=actor;asset.save()
    obj.created_by=actor;obj.full_clean();obj.save();return obj


@transaction.atomic
def decide(model,pk,actor,decision,reason,revision=None):
    candidate=model.objects.get(pk=pk)
    fid=candidate.budget.facility_id if model==OperatingExpense else candidate.case.facility_id if model==CorrectiveAction else candidate.facility_id
    facility_lock(actor,fid)
    obj=model.objects.select_for_update().get(pk=pk);reason_required(reason)
    if model==StaffChecklist:
        if decision=='acknowledge':
            if actor.pk!=obj.staff_id:raise PermissionDenied
            if not obj.acknowledged_at:obj.acknowledged_at=timezone.now()
        elif decision=='complete':
            if actor.pk!=obj.owner_id:raise PermissionDenied
            if obj.completed_at:return obj
            obj.completed_at=timezone.now();obj.evidence=reason
        elif decision=='review':
            supervisor(actor,obj.owner_id)
            if actor.pk==obj.staff_id:raise ValidationError('Staff cannot review their own checklist.')
            if not obj.completed_at or (obj.kind in ('policy','training') and not obj.acknowledged_at):raise ValidationError('Complete the item and obtain the staff acknowledgment first.')
            if obj.kind=='offboarding':
                from apps.encounters.models import Encounter
                from apps.billing.models import CashSession
                from .models import DutyShift, Attendance, WorkTask
                # Review cannot silently strand live patient work or an open shift.
                if CashSession.objects.filter(opened_by=obj.staff,close_time__isnull=True).exists() or Encounter.objects.filter(clinician=obj.staff,status='open').exists() or Attendance.objects.filter(staff=obj.staff,clock_out__isnull=True).exists() or WorkTask.objects.filter(owner=obj.staff,status__in=['open','in_progress']).exists() or DutyShift.objects.filter(staff=obj.staff,status='published',ends_at__gt=timezone.now()).exists():raise ValidationError('Reassign open visits/tasks, close attendance/cash sessions and cancel or cover future duties before offboarding approval.')
                if obj.staff.is_superuser:raise ValidationError('System superuser offboarding requires another system administrator through account administration.')
                # Only admins can deactivate access; managers can track the checklist.
                if not (actor.is_superuser or actor.role=='admin'):raise PermissionDenied
                obj.staff.is_active=False;obj.staff.save(update_fields=['is_active'])
            obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason
        else:raise ValidationError('Unknown checklist action.')
    elif model==CorrectiveAction:
        manager(actor)
        if decision!='complete':raise ValidationError('Choose complete.')
        if actor.pk!=obj.owner_id:raise PermissionDenied
        if obj.completed_at:return obj
        obj.completed_at=timezone.now();obj.evidence=reason
    elif model==ManagementCase:
        manager(actor)
        if revision!=obj.revision:raise ValidationError('Case changed. Reload before acting.')
        if decision=='resolve':
            if actor.pk!=obj.owner_id:raise PermissionDenied
            if obj.status!='open' or obj.actions.filter(completed_at__isnull=True).exists():raise ValidationError('Complete corrective actions before requesting closure.')
            obj.resolution=reason;obj.status='review'
        elif decision=='close':
            supervisor(actor,obj.owner_id)
            if obj.status!='review':raise ValidationError('The owner must submit a resolution first.')
            obj.status='closed';obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason
        elif decision=='reopen':obj.status='open';obj.review_reason=reason;obj.reviewed_by=None;obj.reviewed_at=None
        else:raise ValidationError('Unknown case action.')
        obj.revision+=1
    elif model in (OperatingBudget,OperatingExpense):
        supervisor(actor,obj.created_by_id)
        if decision not in ('approved','rejected'):raise ValidationError('Choose approve or reject.')
        if obj.status not in ('draft','requested'):return obj
        if decision=='approved':
            require_approval(actor,fid,'budget' if model==OperatingBudget else 'expense',obj.amount)
            if model==OperatingBudget:
                if OperatingBudget.objects.filter(facility_id=fid,cost_centre=obj.cost_centre,status='approved',starts_on__lte=obj.ends_on,ends_on__gte=obj.starts_on).exclude(pk=obj.pk).exists():raise ValidationError('This cost centre already has an overlapping approved budget.')
            else:
                budget=OperatingBudget.objects.select_for_update().get(pk=obj.budget_id)
                used=budget.expenses.filter(status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0')
                if budget.status!='approved' or used+obj.amount>budget.amount:raise ValidationError('Approved expenses would exceed this budget.')
        obj.status=decision;obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason
    else:raise ValidationError('Unknown management record.')
    obj._history_user=actor;obj.save();return obj
