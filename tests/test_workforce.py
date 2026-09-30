from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from apps.accounts.models import User, Facility, Department, StaffProfile
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.operations.models import DutyShift, Attendance, StaffLeave, DutyAssignment
from apps.operations import workforce_services as s

pytestmark=pytest.mark.django_db

@pytest.fixture
def team():
    facility=Facility.objects.create(name='Staff test facility')
    other=Facility.objects.create(name='Other facility')
    department=Department.objects.create(facility=facility,name='Outpatient')
    users={}
    for name,role in [('manager','manager'),('manager2','manager'),('doctor','clinician'),('cover','clinician'),('nurse','nurse'),('reception','reception'),('outsider','manager')]:
        u=User.objects.create_user(username='duty-'+name,role=role)
        StaffProfile.objects.update_or_create(user=u,defaults={'facility':other if name=='outsider' else facility,'department':None if name=='outsider' else department})
        users[name]=u
    return SimpleNamespace(f=facility,other=other,dept=department,now=timezone.now(),**users)


def shift(t,staff=None,start=None,end=None,publish=True,**kwargs):
    obj=s.create_shift(t.manager,t.f,t.dept,staff or t.doctor,t.manager,start or t.now-timedelta(minutes=10),end or t.now+timedelta(hours=8),**kwargs)[0]
    if publish:s.shift_action(obj.pk,t.manager,'publish',obj.revision)
    obj.refresh_from_db();return obj


def test_publish_conflicts_leave_and_stale_revision(team):
    t=team;a=shift(t)
    b=shift(t,publish=False)
    with pytest.raises(ValidationError,match='overlapping'):s.shift_action(b.pk,t.manager,'publish',b.revision)
    with pytest.raises(ValidationError,match='changed'):s.shift_action(a.pk,t.manager,'cancel',1,'cancel')
    leave=s.request_leave(t.doctor,t.now,t.now+timedelta(hours=2),'Private leave reason')
    with pytest.raises(ValidationError,match='overlapping'):s.review_leave(leave.pk,t.manager,'approved','Reviewed')
    s.shift_action(a.pk,t.manager,'cancel',a.revision,'Cover separately')
    s.review_leave(leave.pk,t.manager,'approved','Reviewed')
    with pytest.raises(ValidationError,match='approved leave'):s.shift_action(b.pk,t.manager,'publish',b.revision)
    with pytest.raises(PermissionDenied):s.create_shift(t.nurse,t.f,t.dept,t.doctor,t.manager,t.now,t.now+timedelta(hours=1))
    with pytest.raises(PermissionDenied):s.shift_action(b.pk,t.outsider,'publish',b.revision)


def test_recurrence_overnight_and_inactive_staff(team):
    t=team;start=t.now.replace(hour=23,minute=0,second=0)+timedelta(days=1)
    rows=s.create_shift(t.manager,t.f,t.dept,t.doctor,t.manager,start,start+timedelta(hours=8),repeat_weeks=3)
    assert len(rows)==3 and rows[-1].starts_at-start==timedelta(weeks=2)
    t.doctor.is_active=False;t.doctor.save()
    with pytest.raises(ValidationError,match='active staff'):s.shift_action(rows[0].pk,t.manager,'publish',1)


def test_clock_break_retry_and_own_access(team):
    t=team;a=shift(t)
    with pytest.raises(PermissionDenied):s.clock(a.pk,t.nurse,'in')
    att=s.clock(a.pk,t.doctor,'in');assert s.clock(a.pk,t.doctor,'in').pk==att.pk
    a.refresh_from_db();s.shift_action(a.pk,t.doctor,'accepting',a.revision)
    s.clock(a.pk,t.doctor,'break');s.clock(a.pk,t.doctor,'break');assert att.breaks.count()==1
    a.refresh_from_db();assert a.availability=='unavailable'
    with pytest.raises(ValidationError,match='end any break'):s.shift_action(a.pk,t.doctor,'accepting',a.revision)
    s.clock(a.pk,t.doctor,'resume');s.clock(a.pk,t.doctor,'out');s.clock(a.pk,t.doctor,'out')
    att.refresh_from_db();assert att.clock_out and att.breaks.get().ended_at
    a.refresh_from_db()
    with pytest.raises(ValidationError,match='cannot be cancelled'):s.shift_action(a.pk,t.manager,'cancel',a.revision,'Wrong shift')


def test_correction_preserves_original_and_reapproves(team):
    t=team;a=shift(t)
    with patch.object(s.timezone,'now',return_value=t.now):att=s.clock(a.pk,t.doctor,'in')
    with patch.object(s.timezone,'now',return_value=t.now+timedelta(hours=2)):s.clock(a.pk,t.doctor,'out')
    att.refresh_from_db();original=(att.clock_in,att.clock_out)
    s.approve_timesheet(att.pk,t.manager,'Reviewed')
    with patch.object(s.timezone,'now',return_value=t.now+timedelta(hours=3)):
        correction=s.request_correction(att.pk,t.doctor,t.now-timedelta(minutes=5),t.now+timedelta(hours=2),15,'Missed clock-in')
    with pytest.raises(PermissionDenied):s.review_correction(correction.pk,t.doctor,'approved','Self')
    s.review_correction(correction.pk,t.manager,'approved','Checked against shift register')
    att.refresh_from_db();assert (att.clock_in,att.clock_out)==original and att.reviewed_at is None
    assert s.attendance_totals(att)['worked_minutes']==110
    s.approve_timesheet(att.pk,t.manager2,'Checked correction')
    with pytest.raises(PermissionDenied):s.approve_timesheet(att.pk,t.doctor,'Self')


def test_cover_requires_acceptance_and_independent_review(team):
    t=team;a=shift(t,start=t.now+timedelta(days=1),end=t.now+timedelta(days=1,hours=8))
    cover=s.request_cover(a.pk,t.doctor,t.cover,'Family commitment')
    with pytest.raises(ValidationError,match='accept first'):s.review_cover(cover.pk,t.manager,'approved','Reviewed')
    with pytest.raises(PermissionDenied):s.review_cover(cover.pk,t.nurse,'accept','')
    s.review_cover(cover.pk,t.cover,'accept','')
    s.review_cover(cover.pk,t.manager,'approved','Coverage confirmed')
    a.refresh_from_db();assert a.staff==t.cover
    s.review_cover(cover.pk,t.manager,'approved','Retry');assert a.history.count()>=3


def test_handover_and_patient_assignment(team):
    t=team;a=shift(t,capacity=1);att=s.clock(a.pk,t.doctor,'in')
    patient=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Duty',gender='F')
    visit=Encounter.objects.create(patient=patient,facility=t.f)
    with pytest.raises(ValidationError,match='accepting'):s.assign_visit(visit.pk,a.pk,t.reception,'Allocation')
    s.shift_action(a.pk,t.doctor,'accepting',a.revision)
    s.assign_visit(visit.pk,a.pk,t.reception,'Allocation');s.assign_visit(visit.pk,a.pk,t.reception,'Retry')
    visit.refresh_from_db();assert visit.clinician==t.doctor and DutyAssignment.objects.count()==1
    visit2=Encounter.objects.create(patient=patient,facility=t.f)
    with pytest.raises(ValidationError,match='capacity'):s.assign_visit(visit2.pk,a.pk,t.reception,'Allocation')
    handover=s.handover(a.pk,t.doctor,t.cover,'Review outstanding task references',t.now+timedelta(hours=8))
    with pytest.raises(PermissionDenied):s.acknowledge_handover(handover.pk,t.nurse,'Read')
    s.acknowledge_handover(handover.pk,t.cover,'Accepted outstanding tasks');handover.refresh_from_db();assert handover.acknowledged_at


def test_workforce_pages_permissions_privacy_and_post(client,team):
    t=team;a=shift(t);leave=s.request_leave(t.doctor,t.now+timedelta(days=2),t.now+timedelta(days=3),'PRIVATE REASON')
    client.force_login(t.nurse)
    assert client.get('/suite/workforce/').status_code==200
    assert b'PRIVATE REASON' not in client.get('/suite/workforce/inbox/').content
    assert client.get('/suite/workforce/directory/').status_code==403
    assert client.post(f'/suite/workforce/action/clock/{a.pk}/',{'decision':'in'}).status_code==403
    client.force_login(t.outsider)
    assert client.get(f'/suite/workforce/shift/{a.pk}/').status_code==404
    client.force_login(t.manager)
    for path in ['','directory/','inbox/','timesheets/','new/shift/','new/credential/']:
        response=client.get('/suite/workforce/'+path);assert response.status_code==200,(path,response.content[:500])
    assert b'PRIVATE REASON' in client.get('/suite/workforce/inbox/').content
    assert client.get(f'/suite/workforce/action/shift/{a.pk}/').status_code==405
    client.force_login(t.doctor)
    assert client.post(f'/suite/workforce/action/clock/{a.pk}/',{'decision':'in'}).status_code==302
    assert Attendance.objects.filter(shift=a).exists()
    assert client.get('/suite/workforce/timesheets/?export=csv').status_code==403
