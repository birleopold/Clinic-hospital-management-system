"""Operation-specific workforce screens never turn a delegated reviewer into HR."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ApprovalGrant, Department, Facility, FacilityAccess, FacilityConfiguration, StaffProfile, User
from apps.operations.models import Attendance, AttendanceCorrection, DutyShift, ShiftCover, ShiftHandover, StaffLeave

pytestmark = pytest.mark.django_db
OPERATIONS = ('attendance_review', 'leave_review', 'cover_review', 'roster_publish')


@pytest.fixture
def workforce_ui():
    facility = Facility.objects.create(name='Delegated workforce')
    other = Facility.objects.create(name='Separate workforce')
    department = Department.objects.create(facility=facility, name='Primary care')
    other_department = Department.objects.create(facility=other, name='Other care')
    users = {}
    for name, role in [('admin', 'admin'), ('manager', 'manager'), ('delegate', 'nurse'),
                       ('doctor', 'clinician'), ('colleague', 'clinician'), ('outsider', 'clinician')]:
        user = User.objects.create_user(username='ui-' + name, role=role)
        StaffProfile.objects.update_or_create(user=user, defaults={
            'facility': other if name == 'outsider' else facility,
            'department': other_department if name == 'outsider' else department,
        })
        users[name] = user
    return SimpleNamespace(f=facility, other=other, dept=department, other_dept=other_department,
                           now=timezone.now(), **users)


def grant(t, operation, user=None, **changes):
    values = dict(facility=t.f, operation=operation, approver=user or t.delegate, maximum=None,
                  starts_at=t.now - timedelta(hours=1), ends_at=t.now + timedelta(days=1),
                  created_by=t.admin, reason='Independent workforce review')
    values.update(changes)
    return ApprovalGrant.objects.create(**values)


def duty(t, staff=None, *, past=False, **changes):
    staff = staff or t.doctor
    profile = staff.staff_profile
    start = t.now - timedelta(days=2) if past else t.now + timedelta(days=2)
    values = dict(facility=profile.facility, department=profile.department, staff=staff,
                  supervisor=t.manager, starts_at=start, ends_at=start + timedelta(hours=4),
                  created_by=t.manager, status='published' if past else 'draft')
    values.update(changes)
    return DutyShift.objects.create(**values)


def attendance(t, staff=None, **changes):
    shift = duty(t, staff, past=True)
    values = dict(shift=shift, staff=shift.staff, created_by=shift.staff,
                  clock_in=shift.starts_at, clock_out=shift.ends_at)
    values.update(changes)
    return Attendance.objects.create(**values)


def correction(t, staff=None, **changes):
    att = attendance(t, staff)
    values = dict(attendance=att, clock_in=att.clock_in, clock_out=att.clock_out,
                  break_minutes=0, reason='Restricted correction', created_by=att.staff)
    values.update(changes)
    return AttendanceCorrection.objects.create(**values)


def leave(t, staff=None, **changes):
    staff = staff or t.doctor
    values = dict(facility=staff.staff_profile.facility, staff=staff,
                  starts_at=t.now + timedelta(days=5), ends_at=t.now + timedelta(days=6),
                  reason='Restricted leave', created_by=staff)
    values.update(changes)
    return StaffLeave.objects.create(**values)


def cover(t, staff=None, **changes):
    shift = duty(t, staff, status='published')
    values = dict(shift=shift, original_staff=shift.staff, replacement=t.colleague,
                  reason='Restricted cover', created_by=shift.staff)
    values.update(changes)
    return ShiftCover.objects.create(**values)


def handover(t, staff=None, **changes):
    shift = duty(t, staff, past=True)
    values = dict(shift=shift, incoming=t.colleague, summary='Restricted handover',
                  due_at=shift.ends_at, created_by=shift.staff)
    values.update(changes)
    return ShiftHandover.objects.create(**values)


def action_url(kind, obj):
    return reverse('suite-workforce-action', args=[kind, obj.pk])


@pytest.mark.parametrize('operation', OPERATIONS)
def test_delegation_scopes_each_inbox_category_to_its_own_workflow(workforce_ui, client, operation):
    t = workforce_ui
    grant(t, operation)
    private = {'leave': leave(t), 'covers': cover(t), 'corrections': correction(t), 'handovers': handover(t)}
    own = {'leave': leave(t, t.delegate), 'covers': cover(t, t.delegate),
           'corrections': correction(t, t.delegate), 'handovers': handover(t, t.delegate)}
    foreign = {'leave': leave(t, t.outsider), 'covers': cover(t, t.outsider),
               'corrections': correction(t, t.outsider), 'handovers': handover(t, t.outsider)}
    scopes = {'leave': 'leave_review', 'covers': 'cover_review', 'corrections': 'attendance_review'}
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce-inbox'))
    assert response.status_code == 200
    assert response.context['workforce_manager'] is False
    for category, obj in private.items():
        visible = {row.pk for row in response.context[category]}
        assert (obj.pk in visible) is (scopes.get(category) == operation)
        assert own[category].pk in visible
        assert foreign[category].pk not in visible
    timesheets = client.get(reverse('suite-workforce-timesheets'))
    visible = {row.pk for row in timesheets.context['page']}
    assert (private['corrections'].attendance_id in visible) is (operation == 'attendance_review')
    assert own['corrections'].attendance_id in visible
    assert foreign['corrections'].attendance_id not in visible


@pytest.mark.parametrize('operation', OPERATIONS)
def test_each_delegate_has_no_manager_setup_export_or_grant_management(workforce_ui, client, operation):
    t = workforce_ui
    grant(t, operation)
    client.force_login(t.delegate)
    denied = [reverse('suite-workforce-directory'), reverse('suite-workforce-timesheets') + '?export=csv',
              '/accounts/approvals/', reverse('suite-workforce-create-for', args=['employment', t.doctor.staff_profile.pk])]
    denied += [reverse('suite-workforce-create', args=[kind]) for kind in ('shift', 'credential', 'coverage', 'attendance-policy')]
    for url in denied:
        assert client.get(url).status_code == 403, url
        if 'timesheets' not in url:
            assert client.post(url, {}).status_code == 403, url
    response = client.get(reverse('suite-workforce'))
    for label in ('Create roster', 'Staff directory', 'Configure coverage', 'Attendance policy'):
        assert label.encode() not in response.content
    assert (b'Publish roster group' in response.content) is (operation == 'roster_publish')


def test_attendance_reviewer_cannot_request_someone_elses_correction(workforce_ui, client):
    t = workforce_ui
    grant(t, 'attendance_review')
    own = attendance(t, t.delegate)
    other = attendance(t)
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce-timesheets'))
    rows = {row.pk: row for row in response.context['page']}
    assert rows[own.pk].can_request_correction is True and rows[own.pk].can_review is False
    assert rows[other.pk].can_request_correction is False and rows[other.pk].can_review is True
    url = reverse('suite-workforce-create-for', args=['correction', other.pk])
    assert url.encode() not in response.content
    assert client.get(url).status_code == 404
    assert client.post(url, {}).status_code == 404
    assert client.get(reverse('suite-workforce-create-for', args=['correction', own.pk])).status_code == 200


@pytest.mark.parametrize('role_name', ['delegate', 'manager'])
@pytest.mark.parametrize('kind', ['leave', 'correction', 'timesheet'])
@pytest.mark.parametrize('relationship', ['subject', 'requester'])
def test_review_flags_exclude_subject_and_requester(workforce_ui, client, role_name, kind, relationship):
    t = workforce_ui
    actor = getattr(t, role_name)
    operation = 'leave_review' if kind == 'leave' else 'attendance_review'
    if role_name == 'delegate':
        grant(t, operation)
    staff = actor if relationship == 'subject' else t.doctor
    creator = actor if relationship == 'requester' else t.doctor
    if kind == 'leave':
        obj = leave(t, staff, created_by=creator)
    elif kind == 'correction':
        obj = correction(t, staff, created_by=creator)
    else:
        obj = attendance(t, staff, created_by=creator)
    client.force_login(actor)
    response = client.get(reverse('suite-workforce-timesheets' if kind == 'timesheet' else 'suite-workforce-inbox'))
    category = {'leave': 'leave', 'correction': 'corrections', 'timesheet': 'page'}[kind]
    row = next(row for row in response.context[category] if row.pk == obj.pk)
    assert row.can_review is False
    assert action_url(kind, obj).encode() not in response.content


@pytest.mark.parametrize('relationship', ['created_by', 'original_staff', 'replacement'])
@pytest.mark.parametrize('side', ['first', 'partner'])
def test_cover_flags_exclude_every_participant_on_both_swap_sides(workforce_ui, client, relationship, side):
    t = workforce_ui
    grant(t, 'cover_review')
    first = cover(t)
    partner = cover(t, t.colleague, replacement=t.doctor, created_by=t.manager, swap_partner=first)
    first.swap_partner = partner
    first.save(update_fields=['swap_partner'])
    target = first if side == 'first' else partner
    setattr(target, relationship, t.delegate)
    target.save(update_fields=[relationship])
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce-inbox'))
    rows = {row.pk: row for row in response.context['covers']}
    assert rows[first.pk].can_review is False and rows[partner.pk].can_review is False
    assert b'Approve</button>' not in response.content


def test_pending_correction_hides_timesheet_approval(workforce_ui, client):
    t = workforce_ui
    grant(t, 'attendance_review')
    obj = correction(t)
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce-timesheets'))
    row = next(row for row in response.context['page'] if row.pk == obj.attendance_id)
    assert row.can_review is False
    assert action_url('timesheet', obj.attendance).encode() not in response.content


def test_roster_publisher_sees_scoped_drafts_and_can_publish_individual_and_group(workforce_ui, client):
    t = workforce_ui
    grant(t, 'roster_publish')
    one = duty(t)
    two = duty(t, t.colleague)
    foreign = duty(t, t.outsider)
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce'), {'date': timezone.localdate(one.starts_at).isoformat()})
    assert {row.pk for row in response.context['page']} == {one.pk, two.pk}
    detail = client.get(reverse('suite-workforce-shift', args=[one.pk]))
    assert detail.status_code == 200 and detail.context['shift'].can_publish is True
    assert b'Publish shift' in detail.content and b'Cancel shift' not in detail.content
    assert client.get(reverse('suite-workforce-shift', args=[foreign.pk])).status_code == 404
    response = client.post(action_url('shift', one), {'decision': 'publish', 'revision': one.revision})
    assert response.status_code == 302
    one.refresh_from_db()
    assert one.status == 'published'
    url = reverse('suite-workforce-create', args=['publish'])
    response = client.get(url)
    assert set(response.context['form'].fields['duties'].queryset.values_list('pk', flat=True)) == {two.pk}
    response = client.post(url, {'duties': [two.pk], 'snapshot': response.context['form']['snapshot'].value()})
    assert response.status_code == 302
    two.refresh_from_db()
    assert two.status == 'published'
    for obj in (one, two):
        assert client.post(action_url('shift', obj), {'decision': 'cancel', 'revision': obj.revision, 'reason': 'Tampered action'}).status_code == 403
        obj.refresh_from_db()
        assert obj.status == 'published'


def test_publication_form_rejects_foreign_duties_and_tampered_snapshot(workforce_ui, client):
    t = workforce_ui
    grant(t, 'roster_publish')
    own = duty(t)
    foreign = duty(t, t.outsider)
    client.force_login(t.delegate)
    url = reverse('suite-workforce-create', args=['publish'])
    snapshot = client.get(url).context['form']['snapshot'].value()
    for payload in ({'duties': [foreign.pk], 'snapshot': snapshot},
                    {'duties': [own.pk], 'snapshot': 'tampered'},
                    {'duties': [own.pk], 'snapshot': signing.dumps({'actor': t.doctor.pk, 'revisions': {str(own.pk): own.revision}}, salt='workforce-roster')}):
        response = client.post(url, payload)
        assert response.status_code == 200 and response.context['form'].errors
    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.status == foreign.status == 'draft'
    assert client.post(action_url('shift', foreign), {'decision': 'publish', 'revision': foreign.revision}).status_code == 404


@pytest.mark.parametrize('change', ['expired', 'revoked'])
@pytest.mark.parametrize('kind', ['leave', 'correction', 'timesheet', 'cover', 'individual_publish', 'group_publish'])
def test_stale_review_pages_do_not_authorize_post(workforce_ui, client, change, kind):
    t = workforce_ui
    operation = {'leave': 'leave_review', 'correction': 'attendance_review', 'timesheet': 'attendance_review',
                 'cover': 'cover_review', 'individual_publish': 'roster_publish', 'group_publish': 'roster_publish'}[kind]
    authority = grant(t, operation)
    factories = {'leave': leave, 'correction': correction, 'timesheet': attendance, 'cover': cover,
                 'individual_publish': duty, 'group_publish': duty}
    obj = factories[kind](t)
    client.force_login(t.delegate)
    if kind == 'group_publish':
        url = reverse('suite-workforce-create', args=['publish'])
        response = client.get(url)
        payload = {'duties': [obj.pk], 'snapshot': response.context['form']['snapshot'].value()}
    elif kind == 'individual_publish':
        response = client.get(reverse('suite-workforce-shift', args=[obj.pk]))
        url = action_url('shift', obj)
        payload = {'decision': 'publish', 'revision': obj.revision}
    else:
        response = client.get(reverse('suite-workforce-timesheets' if kind == 'timesheet' else 'suite-workforce-inbox'))
        url = action_url(kind, obj)
        payload = {'decision': 'rejected', 'reason': 'Review after permission changed'}
    assert response.status_code == 200
    if change == 'expired':
        ApprovalGrant.objects.filter(pk=authority.pk).update(ends_at=t.now - timedelta(minutes=1))
    else:
        ApprovalGrant.objects.filter(pk=authority.pk).update(revoked_at=timezone.now(), revoked_by=t.admin)
    assert client.post(url, payload).status_code == 403
    obj.refresh_from_db()
    if kind == 'timesheet':
        assert obj.reviewed_at is None
    else:
        assert obj.status == ('draft' if 'publish' in kind else 'requested')


@pytest.mark.parametrize('operation', ['attendance_review', 'leave_review', 'cover_review'])
def test_tampered_review_post_does_not_use_a_different_workflow_grant(workforce_ui, client, operation):
    t = workforce_ui
    grant(t, 'roster_publish')
    kind, factory = {'attendance_review': ('correction', correction), 'leave_review': ('leave', leave),
                     'cover_review': ('cover', cover)}[operation]
    obj = factory(t)
    client.force_login(t.delegate)
    assert client.post(action_url(kind, obj), {'decision': 'rejected', 'reason': 'Wrong workflow'}).status_code == 403
    obj.refresh_from_db()
    assert obj.status == 'requested'


def test_module_disabled_after_grant_denies_workforce_screens_and_posts(workforce_ui, client):
    t = workforce_ui
    grant(t, 'leave_review')
    obj = leave(t)
    FacilityConfiguration.objects.create(facility=t.f, service_type='custom', display_name='Workforce disabled', configured_by=t.admin, enabled_services=['patients'])
    client.force_login(t.delegate)
    assert client.get(reverse('suite-workforce-inbox')).status_code == 404
    assert client.post(action_url('leave', obj), {'decision': 'rejected', 'reason': 'Disabled module'}).status_code == 404
    obj.refresh_from_db()
    assert obj.status == 'requested'


@pytest.mark.parametrize('change', ['expired', 'revoked', 'future'])
def test_unusable_grants_do_not_expand_read_scope(workforce_ui, client, change):
    t = workforce_ui
    for operation in OPERATIONS:
        authority = grant(t, operation)
        if change == 'expired':
            ApprovalGrant.objects.filter(pk=authority.pk).update(ends_at=t.now - timedelta(minutes=1))
        elif change == 'revoked':
            ApprovalGrant.objects.filter(pk=authority.pk).update(revoked_at=t.now, revoked_by=t.admin)
        else:
            ApprovalGrant.objects.filter(pk=authority.pk).update(starts_at=t.now + timedelta(hours=1))
    leave(t)
    cover(t)
    correction(t)
    handover(t)
    draft = duty(t)
    client.force_login(t.delegate)
    response = client.get(reverse('suite-workforce-inbox'))
    assert all(not response.context[key] for key in ('leave', 'covers', 'corrections', 'handovers'))
    assert not client.get(reverse('suite-workforce-timesheets')).context['page'].object_list
    assert client.get(reverse('suite-workforce-shift', args=[draft.pk])).status_code == 403
    assert client.get(reverse('suite-workforce-create', args=['publish'])).status_code == 403
    assert b'Publish roster group' not in response.content


def test_selected_branch_cannot_substitute_for_real_grant_assignment(workforce_ui, client):
    t = workforce_ui
    t.delegate.role = 'reception'
    t.delegate.save(update_fields=['role'])
    FacilityAccess.objects.create(user=t.delegate, facility=t.other, granted_by=t.admin,
                                  expires_at=t.now + timedelta(days=1), reason='Reception cover')
    for operation in OPERATIONS:
        # Simulate an old imported grant; the real staff assignment is still home.
        grant(t, operation, facility=t.other)
    private = leave(t, t.outsider)
    draft = duty(t, t.outsider)
    client.force_login(t.delegate)
    session = client.session
    session['active_facility_id'] = t.other.pk
    session.save()
    response = client.get(reverse('suite-workforce-inbox'))
    assert response.status_code == 200 and not response.context['leave']
    assert client.get(reverse('suite-workforce-shift', args=[draft.pk])).status_code == 403
    assert client.get(reverse('suite-workforce-create', args=['publish'])).status_code == 403
    assert client.post(action_url('leave', private), {'decision': 'rejected', 'reason': 'Branch session alone'}).status_code == 403
    private.refresh_from_db()
    assert private.status == 'requested'
