"""Narrow workforce grants must never become a role or monetary authority."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import approval_services as s
from apps.accounts.approval_models import FINANCIAL_OPERATIONS, OPERATIONS, WORKFORCE_OPERATIONS
from apps.accounts.approval_views import FinancialGrantForm, WorkforceGrantForm
from apps.accounts.models import (ApprovalGrant, ApprovalPolicy, Facility, FacilityConfiguration,
                                 OwnerSupportReceipt, SecurityEvent, StaffProfile, User)
from apps.operations.models import StaffEmployment
from apps.operations.workforce_services import manager
from tests.test_workforce import team

pytestmark = pytest.mark.django_db


@pytest.fixture
def authority_admin(team):
    user = User.objects.create_user('workforce-authority-admin', role='admin')
    StaffProfile.objects.create(user=user, facility=team.f)
    return user


def grant_data(team, operation='attendance_review', **changes):
    data = dict(facility=team.f, operation=operation, approver=team.nurse, maximum=None,
                starts_at=timezone.now() - timedelta(minutes=1), ends_at=timezone.now() + timedelta(days=1),
                reason='Temporary reviewed workforce responsibility', request_key=uuid.uuid4())
    data.update(changes)
    return data


def employment(team, staff=None, **changes):
    data = dict(facility=team.f, staff=staff or team.nurse, employment_type='permanent', status='active',
                starts_on=timezone.localdate() - timedelta(days=1), created_by=team.manager, reason='Synthetic employment')
    data.update(changes)
    return StaffEmployment.objects.create(**data)


def support(user):
    return OwnerSupportReceipt.objects.create(user=user, nonce=uuid.uuid4(), owner_reference='synthetic-owner',
                                             reason='Audited support', expires_at=timezone.now() + timedelta(hours=1))


def configure_workforce(team, administrator, enabled):
    return FacilityConfiguration.objects.update_or_create(
        facility=team.f, defaults=dict(service_type='custom', display_name='Synthetic facility',
                                      enabled_services=['workforce'] if enabled else ['patients'], configured_by=administrator),
    )[0]


@pytest.mark.parametrize('operation', [key for key, _ in WORKFORCE_OPERATIONS])
def test_workforce_grants_are_narrow_amount_free_and_audited(team, authority_admin, operation):
    data = grant_data(team, operation)
    obj = s.grant(authority_admin, **data)
    assert obj.maximum is None and obj.is_workforce and obj.authority_status == 'active'
    assert s.grant(authority_admin, **data).pk == obj.pk
    assert s.workforce_grant(team.nurse, team.f.pk, operation).pk == obj.pk
    assert s.workforce_allowed(team.nurse, team.f.pk, operation)
    assert s.require_workforce(team.nurse, team.f.pk, operation).pk == obj.pk
    assert not s.workforce_allowed(team.nurse, team.other.pk, operation)
    other = next(key for key, _ in WORKFORCE_OPERATIONS if key != operation)
    assert not s.workforce_allowed(team.nurse, team.f.pk, other)
    assert s.workforce_grant(team.nurse, team.f.pk, other) is None
    with pytest.raises(PermissionDenied):
        manager(team.nurse)
    event = SecurityEvent.objects.get(event='approval_authority_granted', target=team.nurse)
    assert event.actor == authority_admin and operation in event.reason and 'UGX' not in event.reason
    team.nurse.refresh_from_db()
    assert team.nurse.role == 'nurse' and not team.nurse.is_superuser


@pytest.mark.parametrize('change', [
    'inactive', 'transferred', 'unassigned', 'suspended', 'onboarding', 'ended',
    'future_employment', 'expired_employment', 'future_grant', 'expired_grant', 'revoked',
    'inactive_facility', 'disabled_module', 'support', 'wrong_branch',
])
def test_live_authority_invalidates_without_trusting_cached_actor(team, authority_admin, change):
    obj = s.grant(authority_admin, **grant_data(team))
    # Prime common request caches. Every guard must still read current authority.
    assert team.nurse.staff_profile.facility_id == team.f.pk
    team.nurse._owner_support_account = False
    team.nurse._service_profile = configure_workforce(team, authority_admin, True)
    assert s.workforce_allowed(team.nurse, team.f.pk, 'attendance_review')
    if change == 'inactive':
        User.objects.filter(pk=team.nurse.pk).update(is_active=False)
    elif change == 'transferred':
        StaffProfile.objects.filter(user=team.nurse).update(facility=team.other)
        team.nurse._active_facility_id = team.f.pk
    elif change == 'unassigned':
        StaffProfile.objects.filter(user=team.nurse).update(facility=None)
        team.nurse._active_facility_id = team.f.pk
    elif change in ('suspended', 'onboarding', 'ended'):
        employment(team, status=change, ends_on=timezone.localdate() if change == 'ended' else None)
    elif change == 'future_employment':
        employment(team, starts_on=timezone.localdate() + timedelta(days=1))
    elif change == 'expired_employment':
        employment(team, starts_on=timezone.localdate() - timedelta(days=3), ends_on=timezone.localdate() - timedelta(days=1))
    elif change == 'future_grant':
        ApprovalGrant.objects.filter(pk=obj.pk).update(starts_at=timezone.now() + timedelta(hours=1))
    elif change == 'expired_grant':
        ApprovalGrant.objects.filter(pk=obj.pk).update(ends_at=timezone.now())
    elif change == 'revoked':
        s.revoke(authority_admin, obj.pk, 'Duty completed')
    elif change == 'inactive_facility':
        Facility.objects.filter(pk=team.f.pk).update(is_active=False)
    elif change == 'disabled_module':
        configure_workforce(team, authority_admin, False)
    elif change == 'support':
        support(team.nurse)
    elif change == 'wrong_branch':
        team.nurse._active_facility_id = team.other.pk
    assert s.workforce_grant(team.nurse, team.f.pk, 'attendance_review') is None
    assert not s.workforce_allowed(team.nurse, team.f.pk, 'attendance_review')
    with pytest.raises(PermissionDenied):
        s.require_workforce(team.nurse, team.f.pk, 'attendance_review')


def test_employment_inclusive_end_and_legacy_assignment(team, authority_admin):
    first = s.grant(authority_admin, **grant_data(team))
    assert s.require_workforce(team.nurse, team.f.pk, 'attendance_review') == first
    employment(team, starts_on=timezone.localdate(), ends_on=timezone.localdate())
    assert s.workforce_allowed(team.nurse, team.f.pk, 'attendance_review')


@pytest.mark.parametrize('role', ['manager', 'admin', 'superuser'])
def test_native_roles_keep_access_but_current_database_activity_and_module_apply(team, authority_admin, role):
    actor = team.manager if role == 'manager' else authority_admin
    if role == 'superuser':
        actor = User.objects.create_superuser('global-authority-admin', email='', password='synthetic-test')
    assert s.workforce_allowed(actor, team.f.pk, 'leave_review')
    assert s.require_workforce(actor, team.f.pk, 'leave_review') is None
    # An owner support ticket does not expand native roles, nor remove existing support work.
    support(actor)
    assert s.workforce_allowed(actor, team.f.pk, 'leave_review')
    assert s.workforce_grant(actor, team.f.pk, 'leave_review') is None
    configure_workforce(team, authority_admin, False)
    assert not s.workforce_allowed(actor, team.f.pk, 'leave_review')
    with pytest.raises(PermissionDenied):
        s.require_workforce(actor, team.f.pk, 'leave_review')
    configure_workforce(team, authority_admin, True)
    User.objects.filter(pk=actor.pk).update(is_active=False)
    assert not s.workforce_allowed(actor, team.f.pk, 'leave_review')


def test_fresh_native_role_and_assignment_are_used(team, authority_admin):
    assert s.workforce_allowed(team.manager, team.f.pk, 'leave_review')
    User.objects.filter(pk=team.manager.pk).update(role='nurse')
    assert not s.workforce_allowed(team.manager, team.f.pk, 'leave_review')
    StaffProfile.objects.filter(user=authority_admin).update(facility=team.other)
    assert not s.workforce_allowed(authority_admin, team.f.pk, 'leave_review')


@pytest.mark.parametrize('operation', ['expense', 'credit', 'unknown', None])
def test_workforce_guards_reject_nonworkforce_and_anonymous(team, operation):
    assert s.workforce_grant(team.manager, team.f.pk, operation) is None
    assert not s.workforce_allowed(team.manager, team.f.pk, operation)
    with pytest.raises(PermissionDenied):
        s.require_workforce(team.manager, team.f.pk, operation)
    assert not s.workforce_allowed(AnonymousUser(), team.f.pk, 'attendance_review')
    with pytest.raises(PermissionDenied):
        s.require_workforce(AnonymousUser(), team.f.pk, 'attendance_review')


@pytest.mark.parametrize('operation', [key for key, _ in FINANCIAL_OPERATIONS])
def test_workforce_never_satisfies_financial_matrix(team, authority_admin, operation):
    s.grant(authority_admin, **grant_data(team, approver=team.manager2))
    s.configure(authority_admin, team.f.pk, operation, True, 0, 'Financial policy remains independent')
    with pytest.raises(ValidationError, match='authority'):
        s.require(team.manager2, team.f.pk, operation, 0)
    assert OPERATIONS == FINANCIAL_OPERATIONS
    with pytest.raises(ValidationError):
        s.configure(authority_admin, team.f.pk, 'attendance_review', True, 0, 'Not financial')
    assert not ApprovalPolicy.objects.filter(operation='attendance_review').exists()


def test_grant_management_rejects_self_other_facility_support_and_ineligible_employment(team, authority_admin):
    for recipient in (authority_admin, team.outsider):
        with pytest.raises(ValidationError):
            s.grant(authority_admin, **grant_data(team, approver=recipient))
    employment(team, status='suspended')
    with pytest.raises(ValidationError, match='employment'):
        s.grant(authority_admin, **grant_data(team))
    support(team.manager2)
    team.manager2._owner_support_account = False
    for operation, amount in [('attendance_review', None), ('expense', Decimal(100))]:
        with pytest.raises(ValidationError, match='support'):
            s.grant(authority_admin, **grant_data(team, operation, approver=team.manager2, maximum=amount))
    support(authority_admin)
    authority_admin._owner_support_account = False
    with pytest.raises(PermissionDenied):
        s.grant(authority_admin, **grant_data(team, approver=team.doctor))
    with pytest.raises(PermissionDenied):
        s.configure(authority_admin, team.f.pk, 'expense', True, 0, 'Support is not permanent')


def test_delegates_cannot_manage_authority_and_expiry_revocation_do_not_change_roles(team, authority_admin):
    obj = s.grant(authority_admin, **grant_data(team))
    with pytest.raises(PermissionDenied):
        s.grant(team.nurse, **grant_data(team, approver=team.doctor))
    with pytest.raises(PermissionDenied):
        s.revoke(team.nurse, obj.pk, 'Cannot revoke')
    with pytest.raises(PermissionDenied):
        s.configure(team.nurse, team.f.pk, 'expense', True, 0, 'Cannot configure')
    s.revoke(authority_admin, obj.pk, 'Ended')
    obj.refresh_from_db()
    assert obj.authority_status == 'revoked'
    assert SecurityEvent.objects.filter(event='approval_authority_revoked', target=team.nurse, actor=authority_admin).count() == 1
    s.revoke(authority_admin, obj.pk, 'Retry')
    assert SecurityEvent.objects.filter(event='approval_authority_revoked', target=team.nurse).count() == 1
    team.nurse.refresh_from_db()
    assert team.nurse.role == 'nurse'


@pytest.mark.parametrize('amount', [None, Decimal('-1'), Decimal('NaN'), Decimal('Infinity'), 'invalid'])
def test_financial_limit_must_be_present_finite_nonnegative(team, authority_admin, amount):
    with pytest.raises(ValidationError, match='finite'):
        s.grant(authority_admin, **grant_data(team, 'expense', approver=team.manager2, maximum=amount))


def test_financial_replays_remain_read_only_after_recipient_changes(team, authority_admin):
    data = grant_data(team, 'expense', approver=team.manager2, maximum=Decimal(100))
    obj = s.grant(authority_admin, **data)
    User.objects.filter(pk=team.manager2.pk).update(is_active=False, role='nurse')
    StaffProfile.objects.filter(user=team.manager2).update(facility=team.other)
    assert s.grant(authority_admin, **data).pk == obj.pk
    assert ApprovalGrant.objects.count() == 1


def test_model_and_database_keep_workforce_and_financial_amounts_separate(team, authority_admin):
    with pytest.raises(ValidationError, match='no monetary'):
        s.grant(authority_admin, **grant_data(team, maximum=0))
    workforce = ApprovalGrant(created_by=authority_admin, **grant_data(team, maximum=0))
    with pytest.raises(ValidationError):
        workforce.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        workforce.save()
    financial = ApprovalGrant(created_by=authority_admin, **grant_data(team, 'expense', approver=team.manager2, maximum=None))
    with pytest.raises(ValidationError):
        financial.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        financial.save()


def test_matrix_separates_recipient_choices_amounts_and_post_validation(client, team, authority_admin):
    client.force_login(authority_admin)
    employment(team, staff=team.cover, status='suspended')
    support(team.manager2)
    response = client.get('/accounts/approvals/')
    assert response.status_code == 200
    financial = response.context['form']
    workforce = response.context['workforce_form']
    assert isinstance(financial, FinancialGrantForm) and isinstance(workforce, WorkforceGrantForm)
    assert dict(financial.fields['operation'].choices) == dict(FINANCIAL_OPERATIONS)
    assert dict(workforce.fields['operation'].choices) == dict(WORKFORCE_OPERATIONS)
    assert financial.fields['maximum'].required and 'maximum' not in workforce.fields
    financial_ids = set(financial.fields['approver'].queryset.values_list('pk', flat=True))
    workforce_ids = set(workforce.fields['approver'].queryset.values_list('pk', flat=True))
    assert financial_ids == {team.manager.pk}
    assert team.nurse.pk in workforce_ids
    assert not workforce_ids.intersection({authority_admin.pk, team.manager2.pk, team.cover.pk, team.outsider.pk})
    data = grant_data(team)
    data.pop('maximum')
    data.update(action='workforce_grant', facility=team.f.pk, approver=team.nurse.pk)
    for change in ({'operation': 'expense'}, {'maximum': '100'}, {'approver': team.outsider.pk},
                   {'approver': authority_admin.pk}, {'approver': team.cover.pk}, {'approver': team.manager2.pk},
                   {'facility': team.other.pk}, {'facility': 'invalid'}):
        assert client.post('/accounts/approvals/', {**data, **change}).status_code == 200
        assert not ApprovalGrant.objects.exists()
    assert client.post('/accounts/approvals/', {**data, 'action': 'grant', 'maximum': 100}).status_code == 200
    assert not ApprovalGrant.objects.exists()
    assert client.post('/accounts/approvals/', data).status_code == 302
    assert client.post('/accounts/approvals/', data).status_code == 302
    assert ApprovalGrant.objects.count() == 1 and ApprovalGrant.objects.get().maximum is None
    configure_workforce(team, authority_admin, False)
    assert client.post('/accounts/approvals/', {**data, 'operation': 'leave_review', 'request_key': uuid.uuid4()}).status_code == 200
    assert ApprovalGrant.objects.count() == 1
    client.force_login(team.nurse)
    assert client.get('/accounts/approvals/').status_code == 403
    assert client.post('/accounts/approvals/', data).status_code == 403


def test_workforce_history_states_have_no_currency(client, team, authority_admin):
    active = s.grant(authority_admin, **grant_data(team))
    scheduled = s.grant(authority_admin, **grant_data(team, 'leave_review', starts_at=timezone.now() + timedelta(hours=1)))
    expired = s.grant(authority_admin, **grant_data(team, 'cover_review'))
    ApprovalGrant.objects.filter(pk=expired.pk).update(ends_at=timezone.now() - timedelta(seconds=1))
    revoked = s.grant(authority_admin, **grant_data(team, 'roster_publish'))
    s.revoke(authority_admin, revoked.pk, 'Handed back to manager')
    client.force_login(authority_admin)
    response = client.get('/accounts/approvals/')
    history = response.content.decode().split('<h2>Authority history</h2>')[1]
    assert all(status in history for status in ('Active', 'Scheduled', 'Expired', 'Revoked'))
    assert 'UGX' not in history and 'None' not in history
    assert active.authority_status == 'active' and scheduled.authority_status == 'scheduled'


def test_workforce_requires_configured_module_when_first_run_setup_is_required(team, authority_admin, settings):
    settings.REQUIRE_SERVICE_SETUP = True
    assert not s.workforce_allowed(team.manager, team.f.pk, 'attendance_review')
    assert not s.workforce_recipients(Facility.objects.filter(pk=team.f.pk)).exists()
    with pytest.raises(ValidationError, match='not enabled'):
        s.grant(authority_admin, **grant_data(team))
    with pytest.raises(PermissionDenied):
        s.require_workforce(team.manager, team.f.pk, 'attendance_review')
    configure_workforce(team, authority_admin, True)
    obj = s.grant(authority_admin, **grant_data(team))
    assert s.require_workforce(team.nurse, team.f.pk, 'attendance_review').pk == obj.pk


def test_unknown_staff_role_cannot_receive_or_use_delegation(team, authority_admin):
    obj = s.grant(authority_admin, **grant_data(team))
    User.objects.filter(pk=team.nurse.pk).update(role='not-a-staff-role')
    assert not s.workforce_allowed(team.nurse, team.f.pk, 'attendance_review')
    assert s.workforce_grant(team.nurse, team.f.pk, 'attendance_review') is None
    with pytest.raises(ValidationError, match='eligible'):
        s.grant(authority_admin, **grant_data(team, 'leave_review'))


@pytest.mark.parametrize('change', ['inactive', 'demoted', 'transferred', 'support'])
@pytest.mark.parametrize('action', ['grant', 'configure', 'revoke'])
def test_administrator_authority_is_rechecked_after_facility_lock(team, authority_admin, monkeypatch, action, change):
    obj = s.grant(authority_admin, **grant_data(team))
    real_lock = s.lock

    def change_after_lock(actor, facility_id):
        result = real_lock(actor, facility_id)
        if change == 'inactive':
            User.objects.filter(pk=actor.pk).update(is_active=False)
        elif change == 'demoted':
            User.objects.filter(pk=actor.pk).update(role='manager')
        elif change == 'transferred':
            StaffProfile.objects.filter(user=actor).update(facility=team.other)
        else:
            support(actor)
        return result

    monkeypatch.setattr(s, 'lock', change_after_lock)
    with pytest.raises(PermissionDenied):
        if action == 'grant':
            s.grant(authority_admin, **grant_data(team, 'leave_review'))
        elif action == 'configure':
            s.configure(authority_admin, team.f.pk, 'expense', True, 0, 'Policy review')
        else:
            s.revoke(authority_admin, obj.pk, 'Revoke after review')
    obj.refresh_from_db()
    assert obj.revoked_at is None and ApprovalGrant.objects.count() == 1
    assert not ApprovalPolicy.objects.exists()
