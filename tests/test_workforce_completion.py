"""Completion regressions for facility-scoped workforce policy and lifecycle."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.models import User, Facility, Department, StaffProfile
from apps.operations.models import StaffCredential, StaffEmployment, DutyShift, Attendance, AttendancePolicy
from apps.operations import workforce_services as s

pytestmark = pytest.mark.django_db


@pytest.fixture
def workforce():
    facility=Facility.objects.create(name='Workforce completion')
    other=Facility.objects.create(name='Other employer')
    department=Department.objects.create(facility=facility,name='Clinic')
    users={}
    for name,role in [('manager','manager'),('doctor','clinician'),('doctor2','clinician'),('nurse','nurse'),('outsider','manager')]:
        user=User.objects.create_user(username='completion-'+name,role=role)
        StaffProfile.objects.update_or_create(user=user,defaults={'facility':other if name=='outsider' else facility,'department':None if name=='outsider' else department})
        users[name]=user
    return SimpleNamespace(f=facility,other=other,dept=department,now=timezone.now(),**users)


def draft(t, staff=None, start=None, end=None, **kwargs):
    start=start or t.now+timedelta(days=1)
    return s.create_shift(t.manager,t.f,t.dept,staff or t.doctor,t.manager,start,end or start+timedelta(hours=8),**kwargs)[0]


def employment(t, staff=None, **kwargs):
    data={'employment_type':'permanent','status':'active','starts_on':timezone.localdate()-timedelta(days=30),'ends_on':None,'reason':'Verified employment','revision':0}
    data.update(kwargs)
    return s.save_employment(t.manager,(staff or t.doctor).staff_profile.pk,**data)


def credential(t, **kwargs):
    data={'facility':t.f,'staff':t.doctor,'specialty':'General practice','credential':'Medical license','reference':'LICENSE-A','expires_on':timezone.localdate()+timedelta(days=10),'verified_on':timezone.localdate()}
    data.update(kwargs)
    return s.record_credential(t.manager,**data)


def coverage(t, **kwargs):
    data={'department':t.dept,'role':'clinician','minimum_staff':2,'include_on_call':False,'enabled':True,'reason':'Clinic service requirement'}
    data.update(kwargs)
    return s.save_coverage_rule(t.manager,**data)


def policy(t, **kwargs):
    data={'facility':t.f,'effective_from':timezone.localdate(),'grace_minutes':5,'rounding_minutes':15,'rounding_mode':'nearest','reason':'Configured attendance review'}
    data.update(kwargs)
    return s.create_attendance_policy(t.manager,**data)


def test_employment_dates_state_and_stale_edits(workforce):
    t=workforce
    with pytest.raises(ValidationError,match='end date'):employment(t,employment_type='fixed_term')
    obj=employment(t,status='onboarding')
    with pytest.raises(ValidationError,match='employment'):draft(t)
    with pytest.raises(ValidationError,match='changed'):employment(t,revision=0)
    employment(t,status='active',revision=obj.revision)
    shift=draft(t);s.shift_action(shift.pk,t.manager,'publish',shift.revision)
    with pytest.raises(ValidationError,match='Cancel or reassign'):employment(t,status='suspended',revision=2)
    shift.refresh_from_db();s.shift_action(shift.pk,t.manager,'cancel',shift.revision,'Change staffing')
    ended=employment(t,status='ended',ends_on=timezone.localdate(),revision=2)
    assert t.doctor.is_active  # Employment edits do not silently change account access.
    with pytest.raises(ValidationError,match='Re-employment'):employment(t,status='active',revision=ended.revision)
    employment(t,status='onboarding',starts_on=timezone.localdate()+timedelta(days=2),revision=ended.revision)
    assert StaffEmployment.objects.get(pk=obj.pk).history.count()==4


def test_employment_guards_recurrence_and_full_interval(workforce):
    t=workforce
    employment(t,ends_on=timezone.localdate(t.now+timedelta(days=3)))
    draft(t)
    with pytest.raises(ValidationError,match='full duty interval'):draft(t,repeat_weeks=2)
    assert DutyShift.objects.count()==1


def test_employment_scope_and_non_manager_permissions(workforce):
    t=workforce
    data={'employment_type':'permanent','status':'active','starts_on':timezone.localdate(),'ends_on':None,'reason':'Review'}
    with pytest.raises(PermissionDenied):s.save_employment(t.nurse,t.doctor.staff_profile.pk,**data)
    with pytest.raises(PermissionDenied):s.save_employment(t.outsider,t.doctor.staff_profile.pk,**data)


def test_credential_renewal_supersedes_once_and_retains_original(workforce,client):
    t=workforce;old=credential(t)
    new=credential(t,supersedes=old,reference='LICENSE-B',expires_on=old.expires_on+timedelta(days=365))
    old.refresh_from_db()
    assert old.renewal==new and old.reference=='LICENSE-A'
    with pytest.raises(ValidationError,match='already been renewed'):credential(t,supersedes=old,expires_on=new.expires_on+timedelta(days=365))
    client.force_login(t.manager)
    response=client.get('/suite/workforce/directory/')
    assert response.status_code==200
    assert old.pk not in {row.pk for row in response.context['expiring']}
    assert b'LICENSE-A' in response.content and b'LICENSE-B' in response.content


@pytest.mark.parametrize('changes,match',[
    ({'verified_on':None},'Verify the renewal'),
    ({'credential':'Other license'},'must match'),
    ({'expires_on':timezone.localdate()},'extend'),
])
def test_credential_renewal_requires_verified_matching_extension(workforce,changes,match):
    t=workforce;old=credential(t)
    with pytest.raises(ValidationError,match=match):credential(t,supersedes=old,**changes)
    assert StaffCredential.objects.count()==1


def test_credential_cross_staff_and_facility_renewal_denied(workforce):
    t=workforce;old=credential(t)
    with pytest.raises(ValidationError,match='must match'):credential(t,supersedes=old,staff=t.doctor2)
    with pytest.raises(PermissionDenied):credential(t,supersedes=old,facility=t.other)


def test_group_publication_is_atomic_and_coverage_cannot_be_bypassed(workforce):
    t=workforce;coverage(t)
    one=draft(t);two=draft(t,t.doctor2)
    with pytest.raises(ValidationError,match='Minimum coverage'):s.shift_action(one.pk,t.manager,'publish',one.revision)
    assert not DutyShift.objects.filter(status='published').exists()
    s.publish_roster(t.manager,{one.pk:one.revision,two.pk:two.revision})
    assert DutyShift.objects.filter(status='published').count()==2
    one.refresh_from_db()
    with pytest.raises(ValidationError,match='Minimum coverage'):s.shift_action(one.pk,t.manager,'cancel',one.revision,'Remove duty')
    one.refresh_from_db();assert one.status=='published'


def test_coverage_checks_interval_edges_and_on_call_setting(workforce):
    t=workforce;rule=coverage(t)
    one=draft(t);two=draft(t,t.doctor2,start=one.starts_at+timedelta(minutes=1),end=one.ends_at,on_call=True)
    with pytest.raises(ValidationError,match='Minimum coverage'):s.publish_roster(t.manager,{one.pk:1,two.pk:1})
    two.starts_at=one.starts_at;two.save()
    with pytest.raises(ValidationError,match='Minimum coverage'):s.publish_roster(t.manager,{one.pk:1,two.pk:1})
    coverage(t,rule_id=rule.pk,revision=rule.revision,include_on_call=True)
    s.publish_roster(t.manager,{one.pk:1,two.pk:1})
    assert DutyShift.objects.filter(status='published').count()==2


def test_separate_weeks_do_not_require_coverage_between_roster_intervals(workforce):
    t=workforce;coverage(t,minimum_staff=1)
    rows=s.create_shift(t.manager,t.f,t.dept,t.doctor,t.manager,t.now+timedelta(days=1),t.now+timedelta(days=1,hours=8),repeat_weeks=2)
    s.publish_roster(t.manager,{row.pk:row.revision for row in rows})
    assert DutyShift.objects.filter(status='published').count()==2


def test_group_publication_rejects_overlapping_drafts_and_stale_revision(workforce):
    t=workforce;one=draft(t);two=draft(t)
    with pytest.raises(ValidationError,match='overlap'):s.publish_roster(t.manager,{one.pk:1,two.pk:1})
    with pytest.raises(ValidationError,match='changed'):s.publish_roster(t.manager,{one.pk:9})
    with pytest.raises(PermissionDenied):s.publish_roster(t.nurse,{one.pk:1})
    with pytest.raises(PermissionDenied):s.publish_roster(t.outsider,{one.pk:1})
    assert not DutyShift.objects.filter(status='published').exists()


def test_group_publication_rejects_mixed_facilities(workforce):
    t=workforce;one=draft(t)
    other_department=Department.objects.create(facility=t.other,name='Other clinic')
    two=s.create_shift(t.outsider,t.other,other_department,t.outsider,t.outsider,t.now+timedelta(days=1),t.now+timedelta(days=1,hours=8))[0]
    with pytest.raises(ValidationError,match='one facility'):s.publish_roster(t.manager,{one.pk:1,two.pk:1})


def test_policy_snapshot_preserves_raw_events_and_approved_totals(workforce):
    t=workforce;configured=policy(t)
    start=timezone.localtime(t.now).replace(hour=10,minute=0,second=0,microsecond=0)
    duty=draft(t,start=start,end=start+timedelta(hours=8))
    with patch.object(s.timezone,'now',return_value=start):s.shift_action(duty.pk,t.manager,'publish',1)
    with patch.object(s.timezone,'now',return_value=start+timedelta(minutes=7)):att=s.clock(duty.pk,t.doctor,'in')
    with patch.object(s.timezone,'now',return_value=start+timedelta(minutes=69)):s.clock(duty.pk,t.doctor,'out')
    att.refresh_from_db();totals=s.attendance_totals(att)
    assert totals['worked_minutes']==62 and totals['policy_worked_minutes']==60
    assert totals['late_minutes']==7 and totals['policy_late_minutes']==2
    assert totals['policy']['id']==configured.pk
    policy(t,effective_from=timezone.localdate()+timedelta(days=1),grace_minutes=15,rounding_minutes=30)
    assert s.attendance_totals(att)==totals
    assert AttendancePolicy.objects.count()==2


@pytest.mark.parametrize('rounding_mode,expected',[('down',60),('nearest',75),('up',75)])
def test_attendance_rounding_is_explicit_and_deterministic(workforce,rounding_mode,expected):
    t=workforce;duty=draft(t)
    att=Attendance.objects.create(shift=duty,staff=t.doctor,clock_in=duty.starts_at,clock_out=duty.starts_at+timedelta(minutes=67,seconds=30),created_by=t.doctor,policy_snapshot={'grace_minutes':0,'rounding_minutes':15,'rounding_mode':rounding_mode})
    totals=s.attendance_totals(att)
    assert totals['worked_minutes']==67.5 and totals['policy_worked_minutes']==expected


def test_existing_attendance_keeps_exact_totals_after_policy_added(workforce):
    t=workforce;duty=draft(t)
    att=Attendance.objects.create(shift=duty,staff=t.doctor,clock_in=duty.starts_at+timedelta(minutes=3),clock_out=duty.starts_at+timedelta(minutes=65),created_by=t.doctor)
    policy(t)
    totals=s.attendance_totals(att)
    assert totals['policy']=={} and totals['policy_worked_minutes']==62 and totals['policy_late_minutes']==3


def test_attendance_policy_scope_bounds_and_no_backdating(workforce):
    t=workforce
    with pytest.raises(ValidationError,match='backdated'):policy(t,effective_from=timezone.localdate()-timedelta(days=1))
    with pytest.raises(ValidationError,match='supported'):policy(t,rounding_minutes=7)
    with pytest.raises(PermissionDenied):policy(t,facility=t.other)


def test_workforce_completion_forms_are_manager_scoped(workforce,client):
    t=workforce;paths=['new/coverage/','new/publish/','new/attendance-policy/',f'new/employment/{t.doctor.staff_profile.pk}/']
    client.force_login(t.nurse)
    for path in paths:assert client.get('/suite/workforce/'+path).status_code==403
    client.force_login(t.manager)
    for path in paths:assert client.get('/suite/workforce/'+path).status_code==200
    client.force_login(t.outsider)
    assert client.get(f'/suite/workforce/new/employment/{t.doctor.staff_profile.pk}/').status_code==404


def test_group_publish_form_rejects_tampered_snapshot_and_publishes_valid_group(workforce,client):
    t=workforce;coverage(t);one=draft(t);two=draft(t,t.doctor2);client.force_login(t.manager)
    url='/suite/workforce/new/publish/'
    response=client.get(url);snapshot=response.context['form']['snapshot'].value()
    bad=client.post(url,{'duties':[one.pk,two.pk],'snapshot':'changed','reason':'Publish roster'})
    assert bad.status_code==200 and not DutyShift.objects.filter(status='published').exists()
    good=client.post(url,{'duties':[one.pk,two.pk],'snapshot':snapshot,'reason':'Publish roster'})
    assert good.status_code==302 and DutyShift.objects.filter(status='published').count()==2


def test_coverage_ignores_ineligible_imported_and_out_of_window_duties(workforce):
    t=workforce;coverage(t,minimum_staff=1)
    one=draft(t)
    # Model-level imports do not bypass eligibility when coverage is computed.
    employment(t,status='suspended')
    one.status='published';one.save()
    assert s.coverage_gaps(t.dept.pk,one.starts_at,one.ends_at)[0]['scheduled']==0
    outside=draft(t,t.doctor2,start=one.ends_at+timedelta(days=1))
    assert s.coverage_gaps(t.dept.pk,one.starts_at,one.ends_at,proposed=[outside])[0]['scheduled']==0


def test_shared_staff_assignment_helper_allows_onboarding_checklists(workforce):
    t=workforce;employment(t,status='onboarding')
    s.staff_at(t.doctor,t.f.pk)
    with pytest.raises(ValidationError,match='employment'):s.staff_at(t.doctor,t.f.pk,check_employment=True)


def test_open_attendance_can_be_closed_after_employment_end_date(workforce):
    t=workforce;today=timezone.localdate()
    employment(t,ends_on=today)
    # Closing a worked duty remains possible after midnight even though new duty is blocked.
    start=timezone.localtime(t.now).replace(hour=12,minute=0,second=0,microsecond=0)
    duty=draft(t,start=start,end=start+timedelta(minutes=1))
    with patch.object(s.timezone,'now',return_value=start):
        s.shift_action(duty.pk,t.manager,'publish',1)
        att=s.clock(duty.pk,t.doctor,'in')
    with patch.object(s.timezone,'now',return_value=start+timedelta(days=1)):
        s.clock(duty.pk,t.doctor,'out')
    att.refresh_from_db();assert att.clock_out
