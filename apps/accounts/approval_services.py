from decimal import Decimal
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from common.facility_scope import filter_by_facility
from common.mfa import record
from .models import Facility,User,StaffProfile,ApprovalPolicy,ApprovalGrant
from .approval_models import OPERATIONS

def administrator(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role=='admin'):raise PermissionDenied

def lock(actor,facility_id):
    facility=filter_by_facility(Facility.objects.select_for_update(),actor,field='pk').filter(pk=facility_id,is_active=True).first()
    if not facility:raise PermissionDenied
    return facility

@transaction.atomic
def configure(actor,facility_id,operation,enabled,revision,reason):
    administrator(actor);lock(actor,facility_id)
    if operation not in dict(OPERATIONS) or not reason.strip():raise ValidationError('Choose an approval workflow and give a policy reason.')
    obj,created=ApprovalPolicy.objects.get_or_create(facility_id=facility_id,operation=operation)
    if (0 if created else obj.revision)!=revision:raise ValidationError('Policy changed. Reload before updating approval rules.')
    obj.enabled=enabled;obj.revision+=1;obj.save(update_fields=['enabled','revision'])
    record(actor,'approval_policy_changed',f'{facility_id}; {operation}; enabled={enabled}; {reason}'[:250])
    return obj

@transaction.atomic
def grant(actor,**data):
    administrator(actor);lock(actor,data['facility'].pk)
    prior=ApprovalGrant.objects.filter(request_key=data['request_key']).first()
    if prior:
        if prior.created_by_id!=actor.pk or any(getattr(prior,key)!=value for key,value in data.items()):raise ValidationError('Approval grant request conflicts with its original record.')
        return prior
    user=User.objects.select_for_update().get(pk=data['approver'].pk)
    if user.pk==actor.pk:raise ValidationError('Another administrator must grant your approval authority.')
    if not user.is_active or user.role not in ('admin','manager') or not StaffProfile.objects.filter(user=user,facility=data['facility']).exists():raise ValidationError('Choose an active administrator or manager assigned to this facility.')
    if data['operation'] not in dict(OPERATIONS) or not data['reason'].strip():raise ValidationError('Choose a workflow and record the delegation reason.')
    amount=Decimal(data['maximum'])
    if not amount.is_finite() or amount<0:raise ValidationError('Set a finite, nonnegative UGX limit.')
    if not timezone.is_aware(data['starts_at']) or not timezone.is_aware(data['ends_at']) or data['ends_at']<=data['starts_at'] or data['ends_at']<=timezone.now():raise ValidationError('Choose an aware, current or future authority interval with an end after its start.')
    if ApprovalGrant.objects.filter(facility=data['facility'],operation=data['operation'],approver=user,revoked_at__isnull=True,starts_at__lt=data['ends_at'],ends_at__gt=data['starts_at']).exists():raise ValidationError('An overlapping authority already exists. Revoke that grant before replacing it.')
    obj=ApprovalGrant(created_by=actor,**data);obj.full_clean();obj.save()
    record(user,'approval_authority_granted',f'{obj.pk}; {obj.operation}; {obj.maximum} UGX; {obj.reason}'[:250],actor)
    return obj

@transaction.atomic
def revoke(actor,pk,reason):
    administrator(actor)
    candidate=ApprovalGrant.objects.get(pk=pk);lock(actor,candidate.facility_id)
    obj=ApprovalGrant.objects.select_for_update().get(pk=pk)
    if not reason.strip():raise ValidationError('Record a reason for revoking authority.')
    if obj.revoked_at:return obj
    obj.revoked_at=timezone.now();obj.revoked_by=actor;obj.revocation_reason=reason;obj.save(update_fields=['revoked_at','revoked_by','revocation_reason'])
    record(obj.approver,'approval_authority_revoked',f'{obj.pk}; {reason}'[:250],actor)
    return obj

@transaction.atomic
def require(actor,facility_id,operation,amount):
    # Existing role/independent-review checks remain mandatory at each call site.
    if facility_id is None:
        if ApprovalPolicy.objects.filter(operation=operation,enabled=True).exists():raise ValidationError('Assign the original record to its facility before approval.')
        return
    lock(actor,facility_id)
    if not ApprovalPolicy.objects.filter(facility_id=facility_id,operation=operation,enabled=True).exists():return
    amount=Decimal(amount)
    if not amount.is_finite() or amount<0:raise ValidationError('Cannot approve an invalid financial amount.')
    now=timezone.now()
    if not ApprovalGrant.objects.filter(facility_id=facility_id,operation=operation,approver=actor,revoked_at__isnull=True,starts_at__lte=now,ends_at__gt=now,maximum__gte=amount).exists():raise ValidationError('Your current approval authority does not cover this UGX amount. Ask the facility administrator to review the approval matrix.')
