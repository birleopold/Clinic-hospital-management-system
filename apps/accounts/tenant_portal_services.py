"""Transactional, owner-only operations for the existing tenant control plane."""
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from common.mfa import record
from common.tenant_runtime import is_owner_support
from .models import TenantDeployment, TenantReadinessCheck, TenantSupportCase, TenantActivity, User, OwnerSupportReceipt
from .tenant_portal_models import CHECKPOINTS
from . import tenant_services


def activity(actor, tenant, event, summary, *, case=None, request_id=None, payload=None):
    row = TenantActivity.objects.create(tenant=tenant, actor=actor, event=event, summary=summary[:600], case=case, request_id=request_id, request_payload=payload or {})
    if actor:record(actor, event, f'{tenant.key}; {summary}'[:250])
    return row


def replay(actor, tenant, request_id, payload):
    if not request_id:return None
    try:request_id = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):raise ValidationError('Reload this form before submitting it.')
    previous = TenantActivity.objects.filter(request_id=request_id).first()
    if previous and (previous.actor_id != actor.pk or previous.tenant_id != tenant.pk or previous.request_payload != payload):
        raise ValidationError('This request has already been used for different changes. Reload the form.')
    return previous


def _locked(actor, pk):
    tenant_services.owner(actor)
    tenant = TenantDeployment.objects.select_for_update().get(pk=pk)
    tenant_services.owner(actor)
    return tenant


def _revision(tenant, revision):
    if tenant.revision != revision:raise ValidationError('Tenant changed. Reload before saving.')


def _bump(tenant, fields):
    tenant.revision += 1
    tenant.save(update_fields=[*fields, 'revision'])


@transaction.atomic
def update_metadata(actor, pk, revision, request_id, **data):
    tenant = _locked(actor, pk)
    allowed = ('contact_name', 'contact_email', 'contact_phone', 'deployment_label', 'operator_notes')
    if set(data) != set(allowed):raise ValidationError('Submit the complete tenant contact and operations form.')
    payload = {'action': 'metadata', 'revision': revision, **data}
    if replay(actor, tenant, request_id, payload):return tenant
    _revision(tenant, revision)
    for name in allowed:setattr(tenant, name, data[name])
    tenant.full_clean()
    _bump(tenant, allowed)
    activity(actor, tenant, 'tenant_metadata_updated', 'Contact and deployment notes updated.', request_id=request_id, payload=payload)
    return tenant


@transaction.atomic
def configure(actor, pk, revision, request_id, **data):
    tenant = _locked(actor, pk)
    allowed = ('name', 'origin', 'bind_port', 'admin_username', 'service_type', 'services')
    if set(data) != set(allowed):raise ValidationError('Submit the complete initial workspace configuration.')
    data['services'] = sorted(set(data['services']))
    payload = {'action': 'configure', 'revision': revision, **data}
    if replay(actor, tenant, request_id, payload):return tenant
    _revision(tenant, revision)
    if not tenant.configuration_editable:
        raise ValidationError('Initial deployment settings are locked for legacy registrations and after the first bundle or tenant contact. Change live services inside the tenant with its administrator.')
    tenant_services.validate_configuration(data)
    for name in allowed:setattr(tenant, name, data[name])
    tenant.full_clean()
    _bump(tenant, allowed)
    activity(actor, tenant, 'tenant_configuration_updated', 'Initial isolated workspace configuration updated.', request_id=request_id, payload=payload)
    return tenant


@transaction.atomic
def readiness(actor, pk, revision, request_id, step, status, evidence):
    tenant = _locked(actor, pk)
    evidence = evidence.strip()
    payload = {'action': 'readiness', 'revision': revision, 'step': step, 'status': status, 'evidence': evidence}
    if replay(actor, tenant, request_id, payload):return tenant
    _revision(tenant, revision)
    if step not in dict(CHECKPOINTS) or status not in ('pending', 'verified') or not evidence or len(evidence)>500:
        raise ValidationError('Select a setup check and record its evidence or the reason it needs review (maximum 500 characters).')
    if tenant.state == 'retired':raise ValidationError('Retired workspaces cannot be commissioned.')
    check, _ = TenantReadinessCheck.objects.get_or_create(tenant=tenant, step=step, defaults={'evidence': evidence, 'updated_by': actor})
    check.status, check.evidence, check.updated_by = status, evidence, actor
    check.full_clean();check.save()
    _bump(tenant, [])
    activity(actor, tenant, 'tenant_readiness_updated', f'{dict(CHECKPOINTS)[step]}: {status}. {evidence}', request_id=request_id, payload=payload)
    return tenant


def owner_assignees():
    return User.objects.filter(is_superuser=True, is_active=True).exclude(pk__in=OwnerSupportReceipt.objects.values('user_id')).order_by('username')


def _assignee(value):
    if value is None:return None
    pk = getattr(value, 'pk', value)
    user = User.objects.filter(pk=pk, is_superuser=True, is_active=True).first()
    if not user or is_owner_support(user):raise ValidationError('Assign only an active permanent platform owner.')
    return user


@transaction.atomic
def create_case(actor, pk, request_id, *, title, category, priority, detail, assignee=None):
    tenant = _locked(actor, pk)
    assignee = _assignee(assignee)
    title, detail = title.strip(), detail.strip()
    payload = {'action': 'create_case', 'title': title, 'category': category, 'priority': priority, 'detail': detail, 'assignee': assignee.pk if assignee else None}
    previous = replay(actor, tenant, request_id, payload)
    if previous:return previous.case
    case = TenantSupportCase(tenant=tenant, title=title, category=category, priority=priority, detail=detail, assignee=assignee, created_by=actor)
    case.full_clean();case.save()
    activity(actor, tenant, 'tenant_case_opened', f'Case {case.pk}: {case.title}', case=case, request_id=request_id, payload=payload)
    return case


@transaction.atomic
def update_case(actor, tenant_pk, case_pk, revision, request_id, *, status, priority, assignee, resolution, note):
    tenant = _locked(actor, tenant_pk)
    case = TenantSupportCase.objects.select_for_update().get(pk=case_pk, tenant=tenant)
    assignee = _assignee(assignee)
    note, resolution = note.strip(), resolution.strip()
    payload = {'action': 'update_case', 'case': case.pk, 'revision': revision, 'status': status, 'priority': priority, 'assignee': assignee.pk if assignee else None, 'resolution': resolution, 'note': note}
    if replay(actor, tenant, request_id, payload):return case
    if case.revision != revision:raise ValidationError('Support case changed. Reload before saving.')
    if not note or len(note)>500:raise ValidationError('Record a short update (maximum 500 characters).')
    if case.status == 'resolved' and status not in ('resolved', 'open'):raise ValidationError('Reopen a resolved case before resuming work.')
    if status == 'resolved' and not resolution:raise ValidationError('Record the resolution before closing this case.')
    if status == 'in_progress' and not assignee:raise ValidationError('Assign a platform owner before starting work.')
    case.status, case.priority, case.assignee = status, priority, assignee
    case.resolution = resolution
    case.resolved_at = (case.resolved_at or timezone.now()) if status == 'resolved' else None
    case.revision += 1
    case.full_clean();case.save()
    activity(actor, tenant, 'tenant_case_updated', f'Case {case.pk}: {case.get_status_display()}. {note}', case=case, request_id=request_id, payload=payload)
    return case
