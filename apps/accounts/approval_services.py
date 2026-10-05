from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from common.facility_scope import filter_by_facility
from common.mfa import record
from .models import Facility,User,StaffProfile,ApprovalPolicy,ApprovalGrant,FacilityConfiguration,OwnerSupportReceipt
from .approval_models import OPERATIONS, FINANCIAL_OPERATIONS, WORKFORCE_OPERATIONS

def administrator(actor):
    from common.tenant_runtime import require_permanent_administrator
    current = _current_actor(actor)
    if current is None:
        raise PermissionDenied('Permanent access changes require a tenant administrator.')
    require_permanent_administrator(current)
    return current

def lock(actor, facility_id):
    current = _current_actor(actor)
    if current is None:
        raise PermissionDenied
    facility = filter_by_facility(Facility.objects.select_for_update(), current, field='pk').filter(pk=facility_id, is_active=True).first()
    if not facility:
        raise PermissionDenied
    # A cached profile or an assignment changed while waiting cannot retain scope.
    current = _current_actor(actor)
    if current is None or not filter_by_facility(Facility.objects.all(), current, field='pk').filter(pk=facility_id, is_active=True).exists():
        raise PermissionDenied
    return facility


def _administrator_at(actor, facility_id):
    current = administrator(actor)
    if not filter_by_facility(Facility.objects.all(), current, field='pk').filter(pk=facility_id, is_active=True).exists():
        raise PermissionDenied
    return current


@transaction.atomic
def configure(actor,facility_id,operation,enabled,revision,reason):
    actor=administrator(actor);lock(actor,facility_id)
    actor=_administrator_at(actor,facility_id)
    if operation not in dict(OPERATIONS) or not reason.strip():raise ValidationError('Choose an approval workflow and give a policy reason.')
    obj,created=ApprovalPolicy.objects.get_or_create(facility_id=facility_id,operation=operation)
    if (0 if created else obj.revision)!=revision:raise ValidationError('Policy changed. Reload before updating approval rules.')
    obj.enabled=enabled;obj.revision+=1;obj.save(update_fields=['enabled','revision'])
    record(actor,'approval_policy_changed',f'{facility_id}; {operation}; enabled={enabled}; {reason}'[:250])
    return obj

@transaction.atomic
def grant(actor, **data):
    actor = administrator(actor)
    lock(actor, data['facility'].pk)
    actor = _administrator_at(actor, data['facility'].pk)
    operation = data['operation']
    if operation not in dict(FINANCIAL_OPERATIONS + WORKFORCE_OPERATIONS) or not data['reason'].strip():
        raise ValidationError('Choose a workflow and record the delegation reason.')
    is_workforce = operation in dict(WORKFORCE_OPERATIONS)
    if is_workforce:
        if data.get('maximum') is not None:
            raise ValidationError('Workforce authority has no monetary limit.')
        data['maximum'] = None
        if not workforce_enabled(data['facility'].pk):
            raise ValidationError('Workforce is not enabled for this facility.')
    else:
        try:
            amount = Decimal(data.get('maximum'))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError('Set a finite, nonnegative UGX limit.')
        if not amount.is_finite() or amount < 0:
            raise ValidationError('Set a finite, nonnegative UGX limit.')
        data['maximum'] = amount
    user = User.objects.select_for_update().get(pk=data['approver'].pk)
    if user.pk == actor.pk:
        raise ValidationError('Another administrator must grant your approval authority.')
    if OwnerSupportReceipt.objects.filter(user=user).exists():
        raise ValidationError('Temporary owner support cannot receive delegated authority.')
    prior = ApprovalGrant.objects.filter(request_key=data['request_key']).first()
    if prior:
        if prior.created_by_id != actor.pk or any(getattr(prior, key) != value for key, value in data.items()):
            raise ValidationError('Approval grant request conflicts with its original record.')
        return prior
    if is_workforce:
        if not workforce_recipients(Facility.objects.filter(pk=data['facility'].pk)).filter(pk=user.pk).exists():
            raise ValidationError('Choose active staff assigned to this facility with currently eligible employment.')
    elif not user.is_active or user.role not in ('admin', 'manager') or not StaffProfile.objects.filter(user=user, facility=data['facility']).exists():
        raise ValidationError('Choose an active administrator or manager assigned to this facility.')
    if not timezone.is_aware(data['starts_at']) or not timezone.is_aware(data['ends_at']) or data['ends_at'] <= data['starts_at'] or data['ends_at'] <= timezone.now():
        raise ValidationError('Choose an aware, current or future authority interval with an end after its start.')
    if ApprovalGrant.objects.filter(facility=data['facility'], operation=operation, approver=user, revoked_at__isnull=True, starts_at__lt=data['ends_at'], ends_at__gt=data['starts_at']).exists():
        raise ValidationError('An overlapping authority already exists. Revoke that grant before replacing it.')
    obj = ApprovalGrant(created_by=actor, **data)
    obj.full_clean()
    obj.save()
    scope = 'workforce authority' if is_workforce else f'{obj.maximum} UGX'
    record(user, 'approval_authority_granted', f'{obj.pk}; {obj.operation}; {scope}; {obj.reason}'[:250], actor)
    return obj


@transaction.atomic
def revoke(actor,pk,reason):
    actor=administrator(actor)
    candidate=ApprovalGrant.objects.get(pk=pk);lock(actor,candidate.facility_id)
    actor=_administrator_at(actor,candidate.facility_id)
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
    if not ApprovalGrant.objects.filter(facility_id=facility_id,operation=operation,approver=actor,approver__staff_profile__facility_id=facility_id,revoked_at__isnull=True,starts_at__lte=now,ends_at__gt=now,maximum__gte=amount).exists():raise ValidationError('Your current approval authority does not cover this UGX amount. Ask the facility administrator to review the approval matrix.')


def _current_actor(actor):
    """Never let a cached request user, profile or support marker prolong authority."""
    if not getattr(actor, 'is_authenticated', False) or not getattr(actor, 'pk', None):
        return None
    current = User.objects.filter(pk=actor.pk, is_active=True).first()
    if current is not None and getattr(actor, '_active_facility_id', None):
        current._active_facility_id = actor._active_facility_id
    return current


def workforce_enabled(facility_id):
    """Read the target facility's current setup, including for global superusers."""
    if not Facility.objects.filter(pk=facility_id, is_active=True).exists():
        return False
    config = FacilityConfiguration.objects.filter(facility_id=facility_id).first()
    # Unconfigured legacy facilities follow the existing service gate default.
    if config is None:
        return not settings.REQUIRE_SERVICE_SETUP
    return 'workforce' in config.enabled_services


def workforce_facilities(facilities):
    if settings.REQUIRE_SERVICE_SETUP:
        facilities = facilities.filter(configuration__isnull=False)
    disabled = [config.facility_id for config in FacilityConfiguration.objects.filter(facility__in=facilities)
                if 'workforce' not in config.enabled_services]
    return facilities.filter(is_active=True).exclude(pk__in=disabled)


def workforce_recipients(facilities):
    """Real assignments and current employment, independently of branch sessions."""
    from apps.operations.models import StaffEmployment
    today = timezone.localdate()
    employment = StaffEmployment.objects.filter(staff_id=OuterRef('pk'), facility_id=OuterRef('staff_profile__facility_id'))
    eligible = employment.filter(status='active', starts_on__lte=today).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
    return User.objects.filter(is_active=True, role__in=[key for key, _ in User.ROLE_CHOICES],
                               staff_profile__facility__in=workforce_facilities(facilities)).exclude(
        pk__in=OwnerSupportReceipt.objects.values('user_id')
    ).annotate(_has_employment=Exists(employment), _eligible_employment=Exists(eligible)).filter(
        Q(_has_employment=False) | Q(_eligible_employment=True)
    )


def _workforce_scope(actor, facility_id):
    return workforce_enabled(facility_id) and filter_by_facility(
        Facility.objects.all(), actor, field='pk'
    ).filter(pk=facility_id).exists()


def _matching_workforce_grant(actor, facility_id, operation):
    # Recipients cannot borrow a branch-session selection or a support ticket.
    if not workforce_recipients(Facility.objects.filter(pk=facility_id)).filter(pk=actor.pk).exists():
        return None
    now = timezone.now()
    return ApprovalGrant.objects.filter(
        approver=actor, facility_id=facility_id, operation=operation,
        maximum__isnull=True, revoked_at__isnull=True, starts_at__lte=now, ends_at__gt=now,
    ).order_by('ends_at', 'pk').first()


def workforce_grant(actor, facility_id, operation):
    """Return only a currently usable, narrowly scoped workforce delegation."""
    if operation not in dict(WORKFORCE_OPERATIONS):
        return None
    current = _current_actor(actor)
    if current is None or not _workforce_scope(current, facility_id):
        return None
    return _matching_workforce_grant(current, facility_id, operation)


def workforce_allowed(actor, facility_id, operation):
    """Read-only UI guard. Native role rules remain independent of delegation."""
    if operation not in dict(WORKFORCE_OPERATIONS):
        return False
    current = _current_actor(actor)
    if current is None or not _workforce_scope(current, facility_id):
        return False
    if current.is_superuser or current.role in ('admin', 'manager'):
        return True
    return _matching_workforce_grant(current, facility_id, operation) is not None


@transaction.atomic
def require_workforce(actor, facility_id, operation):
    """Authorize under the facility lock; callers keep their mutation atomic.

    Returns the grant used by a delegate, or None for an existing native role.
    The caller records delegated use together with its successful mutation.
    """
    if operation not in dict(WORKFORCE_OPERATIONS):
        raise PermissionDenied('This is not a delegable workforce operation.')
    current = _current_actor(actor)
    if current is None:
        raise PermissionDenied('Current workforce authority is required.')
    lock(current, facility_id)
    # Re-read after acquiring the shared grant/revocation/employment lock.
    current = _current_actor(actor)
    if current is None or not _workforce_scope(current, facility_id):
        raise PermissionDenied('This workforce service is not available in this facility.')
    if current.is_superuser or current.role in ('admin', 'manager'):
        return None
    authority = _matching_workforce_grant(current, facility_id, operation)
    if authority is None:
        raise PermissionDenied('Your current authority does not cover this workforce action.')
    return authority
