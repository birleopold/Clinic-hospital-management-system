"""Delegation is an operation-scoped authority, never a staff role promotion."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from apps.accounts import approval_services as approvals
from apps.accounts.models import ApprovalGrant, Department, Facility, SecurityEvent, StaffProfile, User
from apps.operations import workforce_services as s
from apps.operations.finance_services import supervisor
from apps.operations.models import Attendance, DutyShift, ShiftCover, StaffLeave

pytestmark = pytest.mark.django_db


@pytest.fixture
def workforce_delegation():
    facility = Facility.objects.create(name='Delegated workforce')
    other = Facility.objects.create(name='Other delegated workforce')
    department = Department.objects.create(facility=facility, name='Clinic')
    users = {}
    for name, role in [('admin', 'admin'), ('manager', 'manager'), ('delegate', 'nurse'), ('doctor', 'clinician'), ('replacement', 'clinician'), ('outside', 'nurse')]:
        user = User.objects.create_user(username='delegation-' + name, role=role)
        StaffProfile.objects.update_or_create(user=user, defaults={'facility': other if name == 'outside' else facility})
        users[name] = user
    return SimpleNamespace(f=facility, other=other, dept=department, now=timezone.now(), **users)


def grant(t, operation, user=None):
    return approvals.grant(t.admin, facility=t.f, operation=operation, approver=user or t.delegate,
        maximum=None, starts_at=t.now - timedelta(minutes=1), ends_at=t.now + timedelta(hours=2),
        reason='Temporary independently reviewed workforce duty', request_key=uuid4())


def duty(t, staff=None, days=1, publish=False):
    start = t.now + timedelta(days=days)
    obj = s.create_shift(t.manager, t.f, t.dept, staff or t.doctor, t.manager, start, start + timedelta(hours=4))[0]
    if publish:
        s.publish_roster(t.manager, {obj.pk: obj.revision})
        obj.refresh_from_db()
    return obj


def attendance(t, creator=None):
    obj = duty(t, days=-1)
    obj.status = 'published'
    obj.save(update_fields=['status'])
    return Attendance.objects.create(shift=obj, staff=t.doctor, clock_in=obj.starts_at,
        clock_out=obj.ends_at, created_by=creator or t.doctor)


def leave(t, creator=None):
    return StaffLeave.objects.create(facility=t.f, staff=t.doctor, starts_at=t.now + timedelta(days=3),
        ends_at=t.now + timedelta(days=4), reason='Leave request', created_by=creator or t.doctor)


def cover(t):
    obj = duty(t, publish=True)
    request = s.request_cover(obj.pk, t.doctor, t.replacement, 'Cover requested')
    s.review_cover(request.pk, t.replacement, 'accept', '')
    return obj, request


def swap(t):
    first = duty(t, publish=True)
    second = duty(t, t.replacement, days=2, publish=True)
    request = s.request_swap(t.doctor, first.pk, second.pk, 'Swap requested')
    s.review_cover(request.pk, t.replacement, 'accept', '')
    s.review_cover(request.swap_partner_id, t.doctor, 'accept', '')
    return first, second, request


def events(actor):
    return SecurityEvent.objects.filter(actor=actor, event='workforce_delegation_used')


def test_delegated_attendance_correction_and_timesheet_audit(workforce_delegation):
    t = workforce_delegation
    authority = grant(t, 'attendance_review')
    att = attendance(t)
    original = (att.clock_in, att.clock_out)
    correction = s.request_correction(att.pk, t.doctor, att.clock_in, att.clock_out, 10, 'Break register')
    s.review_correction(correction.pk, t.delegate, 'approved', 'Independent review')
    s.approve_timesheet(att.pk, t.delegate, 'Effective attendance reviewed')
    att.refresh_from_db()
    assert (att.clock_in, att.clock_out) == original
    assert att.reviewed_by == t.delegate
    assert events(t.delegate).count() == 2
    assert all(f'grant={authority.pk};' in item.reason and 'operation=attendance_review;' in item.reason for item in events(t.delegate))
    assert events(t.delegate).filter(reason__contains=f'record=operations.attendancecorrection:{correction.pk};').exists()
    assert events(t.delegate).filter(reason__contains=f'record=operations.attendance:{att.pk};').exists()
    t.delegate.refresh_from_db()
    assert t.delegate.role == 'nurse' and not t.delegate.is_staff and not t.delegate.is_superuser and not t.delegate.groups.exists()


def test_delegated_leave_review_and_cancellation(workforce_delegation):
    t = workforce_delegation
    grant(t, 'leave_review')
    obj = leave(t)
    s.review_leave(obj.pk, t.delegate, 'approved', 'Coverage confirmed')
    s.review_leave(obj.pk, t.delegate, 'cancelled', 'Leave withdrawn')
    obj.refresh_from_db()
    assert obj.status == 'cancelled' and obj.reviewed_by == t.delegate
    assert events(t.delegate).count() == 2


def test_delegated_cover_and_atomic_swap_preserve_independent_acceptance(workforce_delegation):
    t = workforce_delegation
    grant(t, 'cover_review')
    first, request = cover(t)
    with pytest.raises(PermissionDenied):
        s.review_cover(request.pk, t.delegate, 'accept', '')
    s.review_cover(request.pk, t.delegate, 'approved', 'Coverage confirmed')
    first.refresh_from_db()
    assert first.staff == t.replacement
    # Different days avoid the already-covered duty.
    first = duty(t, days=4, publish=True)
    second = duty(t, t.replacement, days=5, publish=True)
    pair = s.request_swap(t.doctor, first.pk, second.pk, 'Reciprocal swap')
    s.review_cover(pair.pk, t.replacement, 'accept', '')
    with pytest.raises(ValidationError, match='Both replacement'):
        s.review_cover(pair.pk, t.delegate, 'approved', 'Both duties checked')
    assert ShiftCover.objects.filter(pk__in=[pair.pk, pair.swap_partner_id], status='requested').count() == 2
    s.review_cover(pair.swap_partner_id, t.doctor, 'accept', '')
    s.review_cover(pair.pk, t.delegate, 'approved', 'Both duties checked')
    first.refresh_from_db(); second.refresh_from_db()
    assert first.staff == t.replacement and second.staff == t.doctor
    assert events(t.delegate).count() == 3  # One audit entry for each changed request.


def test_delegated_publication_individual_group_coverage_and_atomicity(workforce_delegation):
    t = workforce_delegation
    grant(t, 'roster_publish')
    one = duty(t)
    two = duty(t, t.replacement)
    s.save_coverage_rule(t.manager, department=t.dept, role='clinician', minimum_staff=2,
        include_on_call=False, enabled=True, reason='Both clinics staffed')
    with pytest.raises(ValidationError, match='Minimum coverage'):
        s.shift_action(one.pk, t.delegate, 'publish', one.revision)
    assert not events(t.delegate).exists()
    with pytest.raises(ValidationError, match='changed'):
        s.publish_roster(t.delegate, {one.pk: one.revision, two.pk: two.revision + 1})
    assert not DutyShift.objects.filter(status='published').exists()
    s.publish_roster(t.delegate, {one.pk: one.revision, two.pk: two.revision})
    assert DutyShift.objects.filter(status='published').count() == 2
    assert events(t.delegate).count() == 2
    one.refresh_from_db()
    with pytest.raises(PermissionDenied):
        s.shift_action(one.pk, t.delegate, 'cancel', one.revision, 'Not delegated')


def test_delegated_individual_publisher_can_publish_own_draft(workforce_delegation):
    t = workforce_delegation
    grant(t, 'roster_publish')
    obj = duty(t, t.delegate)
    s.shift_action(obj.pk, t.delegate, 'publish', obj.revision)
    obj.refresh_from_db()
    assert obj.status == 'published'
    assert events(t.delegate).filter(reason__contains=f'record=operations.dutyshift:{obj.pk};').exists()


@pytest.mark.parametrize('operation,other_operation', [
    ('attendance_review', 'leave_review'), ('leave_review', 'cover_review'),
    ('cover_review', 'roster_publish'), ('roster_publish', 'attendance_review'),
])
def test_wrong_capability_cannot_mutate_other_workflows(workforce_delegation, operation, other_operation):
    t = workforce_delegation
    grant(t, other_operation)
    if operation == 'attendance_review':
        obj = attendance(t)
        act = lambda: s.approve_timesheet(obj.pk, t.delegate, 'Wrong authority')
    elif operation == 'leave_review':
        obj = leave(t)
        act = lambda: s.review_leave(obj.pk, t.delegate, 'approved', 'Wrong authority')
    elif operation == 'cover_review':
        _, obj = cover(t)
        act = lambda: s.review_cover(obj.pk, t.delegate, 'approved', 'Wrong authority')
    else:
        obj = duty(t)
        act = lambda: s.publish_roster(t.delegate, {obj.pk: obj.revision})
    with pytest.raises(PermissionDenied): act()
    obj.refresh_from_db()
    assert obj.reviewed_at is None if operation == 'attendance_review' else obj.status in ('draft', 'requested')
    assert not events(t.delegate).exists()


@pytest.mark.parametrize('workflow,identity', [
    ('correction', 'subject'), ('correction', 'requester'),
    ('timesheet', 'subject'), ('timesheet', 'requester'),
    ('leave', 'subject'), ('leave', 'requester'),
    ('cover', 'subject'), ('cover', 'replacement'), ('cover', 'requester'),
    ('swap', 'subject'), ('swap', 'replacement'), ('swap', 'requester'), ('swap', 'other_requester'),
])
def test_delegated_review_excludes_all_requesters_and_participants(workforce_delegation, workflow, identity):
    t = workforce_delegation
    actor = t.doctor if identity == 'subject' else t.replacement if identity == 'replacement' else t.delegate
    operation = 'attendance_review' if workflow in ('correction', 'timesheet') else 'leave_review' if workflow == 'leave' else 'cover_review'
    grant(t, operation, actor)
    if workflow in ('correction', 'timesheet'):
        att = attendance(t, creator=actor if identity == 'requester' and workflow == 'timesheet' else None)
        if workflow == 'correction':
            obj = s.request_correction(att.pk, t.doctor, att.clock_in, att.clock_out, 0, 'Correction')
            if identity == 'requester':
                obj.created_by = actor; obj.save(update_fields=['created_by'])
            act = lambda: s.review_correction(obj.pk, actor, 'approved', 'Self review')
        else:
            obj = att
            act = lambda: s.approve_timesheet(obj.pk, actor, 'Self review')
    elif workflow == 'leave':
        obj = leave(t, creator=actor if identity == 'requester' else None)
        act = lambda: s.review_leave(obj.pk, actor, 'approved', 'Self review')
    else:
        if workflow == 'cover': _, obj = cover(t)
        else: _, _, obj = swap(t)
        if identity == 'requester':
            obj.created_by = actor; obj.save(update_fields=['created_by'])
        elif identity == 'other_requester':
            ShiftCover.objects.filter(pk=obj.swap_partner_id).update(created_by=actor)
        act = lambda: s.review_cover(obj.pk, actor, 'approved', 'Self review')
    with pytest.raises(ValidationError, match='different supervisor'): act()
    obj.refresh_from_db()
    assert obj.reviewed_at is None
    assert not events(actor).exists()


@pytest.mark.parametrize('is_swap', [False, True])
def test_completed_cover_still_checks_authority_and_acceptor(workforce_delegation, is_swap):
    t = workforce_delegation
    if is_swap: _, _, obj = swap(t)
    else: _, obj = cover(t)
    s.review_cover(obj.pk, t.manager, 'approved', 'Independent review')
    with pytest.raises(PermissionDenied): s.review_cover(obj.pk, t.delegate, 'approved', 'Completed is not public')
    with pytest.raises(PermissionDenied): s.review_cover(obj.pk, t.delegate, 'accept', '')
    authority = grant(t, 'cover_review')
    s.review_cover(obj.pk, t.delegate, 'approved', 'Authorized retry')
    assert not events(t.delegate).exists()  # Read-only retry is not a delegated mutation.
    approvals.revoke(t.admin, authority.pk, 'Acting duty ended')
    with pytest.raises(PermissionDenied): s.review_cover(obj.pk, t.delegate, 'approved', 'Revoked retry')


def test_swap_rejects_cross_facility_pair_before_acceptance_or_review(workforce_delegation):
    t = workforce_delegation
    grant(t, 'cover_review')
    first, second, obj = swap(t)
    DutyShift.objects.filter(pk=second.pk).update(facility=t.other)
    for actor, decision in [(t.replacement, 'accept'), (t.delegate, 'approved'), (t.delegate, 'rejected')]:
        with pytest.raises(ValidationError, match='same facility'):
            s.review_cover(obj.pk, actor, decision, 'Malformed swap')
    first.refresh_from_db(); second.refresh_from_db()
    assert first.staff == t.doctor and second.staff == t.replacement
    assert ShiftCover.objects.filter(status='requested').count() == 2
    assert not events(t.delegate).exists()


def test_four_grants_do_not_change_financial_or_manager_services(workforce_delegation):
    t = workforce_delegation
    for operation in ['attendance_review', 'leave_review', 'cover_review', 'roster_publish']:
        grant(t, operation)
    with pytest.raises(PermissionDenied): supervisor(t.delegate, t.doctor.pk)
    with pytest.raises(PermissionDenied): duty(SimpleNamespace(**{**vars(t), 'manager': t.delegate}))
    with pytest.raises(PermissionDenied):
        s.save_coverage_rule(t.delegate, department=t.dept, role='clinician', minimum_staff=1,
            include_on_call=False, enabled=True, reason='No policy delegation')
    with pytest.raises(PermissionDenied):
        s.create_attendance_policy(t.delegate, facility=t.f, effective_from=timezone.localdate(),
            grace_minutes=5, rounding_minutes=0, rounding_mode='nearest', reason='No policy delegation')
    with pytest.raises(PermissionDenied): approvals.configure(t.delegate, t.f.pk, 'purchase', True, 0, 'No grant management')


@pytest.mark.django_db(transaction=True)
def test_postgres_revocation_committed_before_lock_release_blocks_waiting_review(workforce_delegation):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    t = workforce_delegation
    authority = grant(t, 'leave_review')
    obj = leave(t)
    started = Event()

    def attempt():
        close_old_connections()
        try:
            actor = User.objects.get(pk=t.delegate.pk)
            started.set()
            try:
                s.review_leave(obj.pk, actor, 'approved', 'Concurrent authority check')
            except PermissionDenied:
                return 'denied'
            return 'approved'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Facility.objects.select_for_update().get(pk=t.f.pk)
            future = pool.submit(attempt)
            assert started.wait(timeout=10)
            approvals.revoke(t.admin, authority.pk, 'End acting duty before waiting review')
            assert not future.done()
        assert future.result(timeout=20) == 'denied'
    obj.refresh_from_db()
    assert obj.status == 'requested' and not events(t.delegate).exists()


@pytest.mark.parametrize('change', ['future', 'expired', 'exact_expiry', 'revoked', 'deactivated', 'reassigned', 'suspended', 'wrong_facility'])
def test_direct_review_rechecks_current_authority_before_any_mutation(workforce_delegation, change):
    from apps.operations.models import StaffEmployment
    t = workforce_delegation
    authority = grant(t, 'leave_review')
    obj = leave(t)
    if change == 'future':
        ApprovalGrant.objects.filter(pk=authority.pk).update(starts_at=t.now + timedelta(minutes=1))
    elif change in ('expired', 'exact_expiry'):
        ApprovalGrant.objects.filter(pk=authority.pk).update(ends_at=t.now if change == 'exact_expiry' else t.now - timedelta(seconds=1))
    elif change == 'revoked':
        approvals.revoke(t.admin, authority.pk, 'End acting duty')
    elif change == 'deactivated':
        User.objects.filter(pk=t.delegate.pk).update(is_active=False)
    elif change == 'reassigned':
        # Populate the caller's relation cache before the database change.
        assert t.delegate.staff_profile.facility_id == t.f.pk
        StaffProfile.objects.filter(user=t.delegate).update(facility=t.other)
    elif change == 'suspended':
        StaffEmployment.objects.create(staff=t.delegate, facility=t.f, employment_type='permanent',
            status='suspended', starts_on=timezone.localdate()-timedelta(days=1), reason='Suspended duty', created_by=t.admin)
    else:
        ApprovalGrant.objects.filter(pk=authority.pk).update(facility=t.other)
    with patch.object(s.timezone, 'now', return_value=t.now):
        with pytest.raises(PermissionDenied):
            s.review_leave(obj.pk, t.delegate, 'approved', 'Stale browser review')
    obj.refresh_from_db()
    assert obj.status == 'requested' and obj.reviewed_at is None and not events(t.delegate).exists()
