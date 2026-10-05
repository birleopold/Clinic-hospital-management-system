"""Workforce mutations serialize per facility; events retain their original times."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.accounts.models import User, Facility, StaffProfile
from apps.encounters.models import Encounter
from apps.demographics.models import Patient
from common.facility_scope import filter_by_facility
from .finance_services import supervisor
from .models import (DutyShift, Attendance, AttendanceBreak, AttendanceCorrection,
                     StaffLeave, ShiftCover, ShiftHandover, DutyAssignment, StaffCredential,
                     StaffEmployment, DutyCoverageRule, AttendancePolicy)


def manager(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','manager')):
        raise PermissionDenied


def facility_lock(actor, facility_id):
    if not actor.is_active:raise PermissionDenied
    facility=filter_by_facility(Facility.objects.select_for_update(),actor,field='pk').filter(pk=facility_id,is_active=True).first()
    if not facility:raise PermissionDenied
    return facility


def employment_allows(employment,start,end):
    if not employment:return True  # Legacy staff retain eligibility until employment is recorded.
    last=timezone.localdate(end-timedelta(microseconds=1)) if end>start else timezone.localdate(start)
    return employment.status=='active' and timezone.localdate(start)>=employment.starts_on and (not employment.ends_on or last<=employment.ends_on)


def staff_at(staff,facility_id,start=None,end=None,check_employment=False):
    if not staff.is_active or not StaffProfile.objects.filter(user=staff,facility_id=facility_id).exists():
        raise ValidationError('Choose active staff assigned to this facility.')
    # Non-workforce callers also use this helper for onboarding checklist assignees.
    # Employment eligibility is explicit for workforce actions, or a supplied duty interval.
    if check_employment or start is not None or end is not None:
        employment=StaffEmployment.objects.filter(staff=staff,facility_id=facility_id).first()
        start=start or timezone.now();end=end or start
        if not employment_allows(employment,start,end):
            raise ValidationError('Staff employment must be active for the full duty interval.')


def interval(start,end):
    if not timezone.is_aware(start) or not timezone.is_aware(end) or end<=start:
        raise ValidationError('End must be after start; use facility-local dates and times.')


def reason_required(reason):
    if not reason.strip():raise ValidationError('A reason is required.')


def check_conflicts(staff,facility_id,start,end,exclude=None):
    staff_at(staff,facility_id,start,end)
    if DutyShift.objects.filter(staff=staff,status='published',starts_at__lt=end,ends_at__gt=start).exclude(pk=exclude).exists():
        raise ValidationError('This staff member already has an overlapping published duty.')
    if StaffLeave.objects.filter(staff=staff,status='approved',starts_at__lt=end,ends_at__gt=start).exists():
        raise ValidationError('This duty overlaps approved leave.')


@transaction.atomic
def create_shift(actor,facility,department,staff,supervisor,starts_at,ends_at,backup=None,on_call=False,capacity=10,repeat_weeks=1,reason=''):
    manager(actor);facility_lock(actor,facility.pk)
    interval(starts_at,ends_at)
    if not 1<=capacity<=200 or not 1<=repeat_weeks<=12:raise ValidationError('Capacity must be 1–200 and recurrence 1–12 weeks.')
    if department.facility_id!=facility.pk or not department.is_active:raise ValidationError('Choose an active department in this facility.')
    for user in [staff,supervisor]+([backup] if backup else []):staff_at(user,facility.pk,starts_at,ends_at+timedelta(weeks=repeat_weeks-1))
    if backup and backup.pk==staff.pk:raise ValidationError('Backup must be another staff member.')
    if ends_at-starts_at>timedelta(hours=24):raise ValidationError('A shift must be at most 24 hours.')
    shifts=[]
    for week in range(repeat_weeks):
        start=starts_at+timedelta(weeks=week);end=ends_at+timedelta(weeks=week)
        shifts.append(DutyShift.objects.create(created_by=actor,facility=facility,department=department,staff=staff,supervisor=supervisor,backup=backup,starts_at=start,ends_at=end,on_call=on_call,capacity=capacity,reason=reason))
    return shifts


@transaction.atomic
def shift_action(pk,actor,action,revision,reason=''):
    candidate=DutyShift.objects.get(pk=pk);facility_lock(actor,candidate.facility_id)
    shift=DutyShift.objects.select_for_update().get(pk=pk)
    if revision!=shift.revision:raise ValidationError('This shift changed. Reload before acting.')
    if action in ('publish','cancel'):
        manager(actor)
        if action=='publish':
            return publish_roster(actor,{shift.pk:revision},reason)[0]
        else:
            reason_required(reason)
            if Attendance.objects.filter(shift=shift).exists():raise ValidationError('A recorded attendance cannot be cancelled. Close and review attendance instead.')
            if shift.status=='cancelled':return shift
            if shift.status=='published' and shift.ends_at>timezone.now():
                validate_coverage(shift.department_id,max(shift.starts_at,timezone.now()),shift.ends_at,exclude_ids=[shift.pk])
            shift.status='cancelled';shift.availability='unavailable';shift.reason=reason
    elif action in ('accepting','unavailable'):
        if actor.pk!=shift.staff_id:raise PermissionDenied
        if shift.status!='published' or not shift.starts_at<=timezone.now()<shift.ends_at:raise ValidationError('Only a current published duty can accept patients.')
        attendance=Attendance.objects.filter(shift=shift,clock_out__isnull=True).first()
        if action=='accepting':staff_at(actor,shift.facility_id,check_employment=True)
        if action=='accepting' and (not attendance or attendance.breaks.filter(ended_at__isnull=True).exists()):raise ValidationError('Clock in and end any break before accepting patients.')
        shift.availability=action
    else:raise ValidationError('Unknown shift action.')
    shift.revision+=1;shift._history_user=actor;shift.save();return shift


@transaction.atomic
def clock(pk,actor,action):
    candidate=DutyShift.objects.get(pk=pk);facility_lock(actor,candidate.facility_id)
    shift=DutyShift.objects.select_for_update().get(pk=pk)
    if actor.pk!=shift.staff_id:raise PermissionDenied
    now=timezone.now();attendance=Attendance.objects.filter(shift=shift).first()
    if action=='in':
        staff_at(actor,shift.facility_id,check_employment=True)
        if attendance:return attendance
        if shift.status!='published' or not shift.starts_at<=now<shift.ends_at:raise ValidationError('Clock-in requires a current published shift.')
        # User lock also serializes attendance across facility transfers.
        User.objects.select_for_update().get(pk=actor.pk)
        if Attendance.objects.filter(staff=actor,clock_out__isnull=True).exists():raise ValidationError('Close your previous attendance first.')
        attendance=Attendance.objects.create(shift=shift,staff=actor,clock_in=now,created_by=actor,policy_snapshot=attendance_policy_snapshot(shift))
    elif action in ('out','break','resume'):
        if not attendance:raise ValidationError('Clock in first.')
        if attendance.clock_out:
            if action=='out':return attendance
            raise ValidationError('Attendance has already ended.')
        current=attendance.breaks.filter(ended_at__isnull=True).first()
        if action=='break':
            if not current:AttendanceBreak.objects.create(attendance=attendance,started_at=now,created_by=actor)
        elif action=='resume':
            if current:current.ended_at=now;current._history_user=actor;current.save()
        else:
            if current:current.ended_at=now;current._history_user=actor;current.save()
            attendance.clock_out=now;attendance._history_user=actor;attendance.save()
        if action in ('out','break'):
            shift.availability='unavailable';shift.revision+=1;shift._history_user=actor;shift.save()
    else:raise ValidationError('Unknown attendance action.')
    return attendance


def attendance_totals(attendance,now=None):
    now=now or timezone.now()
    correction=attendance.corrections.filter(status='approved').order_by('-reviewed_at','-pk').first()
    if correction:start,end,break_minutes=correction.clock_in,correction.clock_out,correction.break_minutes
    else:
        start,end=attendance.clock_in,attendance.clock_out or now
        break_minutes=sum(max(0,((b.ended_at or end)-b.started_at).total_seconds()/60) for b in attendance.breaks.all())
    worked=max(0,(end-start).total_seconds()/60-break_minutes)
    late=max(0,(start-attendance.shift.starts_at).total_seconds()/60)
    policy=attendance.policy_snapshot or {}
    increment=policy.get('rounding_minutes',0)
    policy_worked=Decimal(str(worked))
    if increment:
        mode={'nearest':ROUND_HALF_UP,'down':ROUND_FLOOR,'up':ROUND_CEILING}[policy['rounding_mode']]
        policy_worked=(policy_worked/Decimal(increment)).quantize(Decimal('1'),rounding=mode)*increment
    return {'start':start,'end':end if attendance.clock_out or correction else None,'break_minutes':round(break_minutes,1),'worked_minutes':round(worked,1),'late_minutes':round(late,1),'overtime_minutes':round(max(0,(end-attendance.shift.ends_at).total_seconds()/60),1),'corrected':bool(correction),
            'policy_worked_minutes':round(float(policy_worked),1),'policy_late_minutes':round(max(0,late-policy.get('grace_minutes',0)),1),'policy':policy}


@transaction.atomic
def request_correction(pk,actor,clock_in,clock_out,break_minutes,reason):
    candidate=Attendance.objects.select_related('shift').get(pk=pk);facility_lock(actor,candidate.shift.facility_id)
    attendance=Attendance.objects.select_for_update().get(pk=pk)
    if actor.pk!=attendance.staff_id:manager(actor)
    reason_required(reason);interval(clock_in,clock_out)
    if not attendance.clock_out and attendance.shift.ends_at>timezone.now():raise ValidationError('A missing clock-out correction is available after the scheduled shift ends.')
    if clock_out>timezone.now() or not 0<=break_minutes<(clock_out-clock_in).total_seconds()/60:raise ValidationError('Check actual times and total break minutes.')
    if attendance.corrections.filter(status='requested').exists():raise ValidationError('A correction already awaits review.')
    return AttendanceCorrection.objects.create(attendance=attendance,clock_in=clock_in,clock_out=clock_out,break_minutes=break_minutes,reason=reason,created_by=actor)


@transaction.atomic
def review_correction(pk,actor,decision,reason):
    candidate=AttendanceCorrection.objects.select_related('attendance__shift').get(pk=pk);facility_lock(actor,candidate.attendance.shift.facility_id)
    obj=AttendanceCorrection.objects.select_for_update().get(pk=pk)
    supervisor(actor,obj.created_by_id)
    if actor.pk==obj.attendance.staff_id:raise ValidationError('A different supervisor must review their staff attendance.')
    reason_required(reason)
    if decision not in ('approved','rejected'):raise ValidationError('Choose approve or reject.')
    if obj.status!='requested':return obj
    if decision=='approved':
        # The effective interval cannot overlap another recorded attendance.
        for other in Attendance.objects.filter(staff=obj.attendance.staff).exclude(pk=obj.attendance_id).select_related('shift'):
            totals=attendance_totals(other)
            if totals['start']<obj.clock_out and (totals['end'] is None or totals['end']>obj.clock_in):raise ValidationError('Corrected times overlap another attendance.')
        att=Attendance.objects.select_for_update().get(pk=obj.attendance_id)
        if not att.clock_out:
            # Close the operational attendance only after independent review. Original in/out
            # evidence and the asserted interval remain available in history and correction.
            if att.shift.ends_at>timezone.now():raise ValidationError('The shift has not ended.')
            if obj.clock_out<att.clock_in:raise ValidationError('Recorded clock-out precedes the original clock-in.')
            for pause in att.breaks.select_for_update().filter(ended_at__isnull=True):
                if pause.started_at>obj.clock_out:raise ValidationError('Clock-out precedes an open break. Resolve the actual event times.')
                pause.ended_at=obj.clock_out;pause._history_user=actor;pause.save()
            att.clock_out=obj.clock_out
            shift=DutyShift.objects.select_for_update().get(pk=att.shift_id)
            shift.availability='unavailable';shift.revision+=1;shift._history_user=actor;shift.save()
        att.reviewed_at=None;att.reviewed_by=None;att.review_reason='';att._history_user=actor;att.save()
    obj.status=decision;obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason;obj._history_user=actor;obj.save();return obj


@transaction.atomic
def approve_timesheet(pk,actor,reason):
    candidate=Attendance.objects.select_related('shift').get(pk=pk);facility_lock(actor,candidate.shift.facility_id)
    obj=Attendance.objects.select_for_update().get(pk=pk);supervisor(actor,obj.staff_id);reason_required(reason)
    if not obj.clock_out or obj.corrections.filter(status='requested').exists():raise ValidationError('Close attendance and resolve corrections first.')
    obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason;obj._history_user=actor;obj.save();return obj


@transaction.atomic
def request_leave(actor,starts_at,ends_at,reason):
    profile=StaffProfile.objects.get(user=actor);facility_lock(actor,profile.facility_id)
    interval(starts_at,ends_at);reason_required(reason)
    if ends_at<=timezone.now():raise ValidationError('Leave must include future time.')
    return StaffLeave.objects.create(facility=profile.facility,staff=actor,starts_at=starts_at,ends_at=ends_at,reason=reason,created_by=actor)


@transaction.atomic
def review_leave(pk,actor,decision,reason):
    candidate=StaffLeave.objects.get(pk=pk);facility_lock(actor,candidate.facility_id)
    obj=StaffLeave.objects.select_for_update().get(pk=pk)
    supervisor(actor,obj.staff_id);reason_required(reason)
    if decision=='cancelled':
        if obj.status!='approved':raise ValidationError('Only approved leave can be cancelled.')
    elif decision not in ('approved','rejected'):raise ValidationError('Unknown leave decision.')
    elif obj.status!='requested':return obj
    if decision=='approved':
        User.objects.select_for_update().get(pk=obj.staff_id)
        check_conflicts(obj.staff,obj.facility_id,obj.starts_at,obj.ends_at)
        from apps.appointments.models import Appointment
        from .models import TheatreCase
        appointments=Appointment.objects.filter(clinician=obj.staff,scheduled_for__lt=obj.ends_at,scheduled_for__gt=obj.starts_at-timedelta(days=1)).exclude(status__in=['cancelled','no_show','completed'])
        if any(a.scheduled_for+timedelta(minutes=a.duration_minutes)>obj.starts_at for a in appointments) or TheatreCase.objects.filter(surgeon=obj.staff,starts_at__lt=obj.ends_at,ends_at__gt=obj.starts_at).exclude(status__in=['cancelled','completed']).exists():raise ValidationError('Reassign existing appointments or theatre cases before approving leave.')
        if Attendance.objects.filter(staff=obj.staff,clock_out__isnull=True).exists():raise ValidationError('Close open attendance before approving leave.')
    obj.status=decision;obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason;obj._history_user=actor;obj.save();return obj


@transaction.atomic
def request_cover(pk,actor,replacement,reason):
    candidate=DutyShift.objects.get(pk=pk);facility_lock(actor,candidate.facility_id)
    shift=DutyShift.objects.select_for_update().get(pk=pk)
    if actor.pk!=shift.staff_id:manager(actor)
    staff_at(replacement,shift.facility_id,shift.starts_at,shift.ends_at);reason_required(reason)
    if shift.status!='published' or shift.starts_at<=timezone.now() or Attendance.objects.filter(shift=shift).exists():raise ValidationError('Only future published, unworked shifts can be covered.')
    if shift.staff_id==replacement.pk or shift.cover_requests.filter(status='requested').exists():raise ValidationError('Choose another staff member; only one cover request may be pending.')
    if replacement.role!=shift.staff.role:raise ValidationError('Replacement must have the same duty role.')
    return ShiftCover.objects.create(shift=shift,original_staff=shift.staff,replacement=replacement,reason=reason,created_by=actor)


@transaction.atomic
def review_cover(pk,actor,decision,reason):
    candidate=ShiftCover.objects.select_related('shift').get(pk=pk);facility_lock(actor,candidate.shift.facility_id)
    obj=ShiftCover.objects.select_for_update().get(pk=pk)
    if obj.swap_partner_id:return review_swap(obj,actor,decision,reason)
    shift=DutyShift.objects.select_for_update().get(pk=obj.shift_id)
    if obj.status!='requested':return obj
    if decision=='accept':
        if actor.pk!=obj.replacement_id:raise PermissionDenied
        obj.accepted_at=timezone.now()
    elif decision in ('approved','rejected'):
        supervisor(actor,obj.created_by_id)
        if actor.pk in (obj.original_staff_id,obj.replacement_id):raise ValidationError('A supervisor outside this cover arrangement must review it.')
        reason_required(reason)
        if decision=='approved':
            if not obj.accepted_at:raise ValidationError('The replacement must accept first.')
            if shift.status!='published' or shift.staff_id!=obj.original_staff_id or shift.starts_at<=timezone.now() or Attendance.objects.filter(shift=shift).exists():raise ValidationError('Shift changed or started; create a fresh arrangement.')
            check_conflicts(obj.replacement,shift.facility_id,shift.starts_at,shift.ends_at,shift.pk)
            if obj.replacement.role!=shift.staff.role:raise ValidationError('Replacement role changed.')
            shift.staff=obj.replacement;shift.availability='unavailable';shift.revision+=1;shift._history_user=actor;shift.save()
        obj.status=decision;obj.reviewed_by=actor;obj.reviewed_at=timezone.now();obj.review_reason=reason
    else:raise ValidationError('Unknown cover action.')
    obj._history_user=actor;obj.save();return obj


@transaction.atomic
def handover(pk,actor,incoming,summary,due_at):
    shift=DutyShift.objects.get(pk=pk);facility_lock(actor,shift.facility_id)
    if actor.pk!=shift.staff_id:raise PermissionDenied
    staff_at(incoming,shift.facility_id,check_employment=True);reason_required(summary)
    if incoming.pk==actor.pk or incoming.role!=actor.role:raise ValidationError('Choose another colleague with the same role.')
    if shift.status!='published' or not Attendance.objects.filter(shift=shift).exists():raise ValidationError('A handover requires a worked published shift.')
    return ShiftHandover.objects.create(shift=shift,incoming=incoming,summary=summary,due_at=due_at,created_by=actor)


@transaction.atomic
def acknowledge_handover(pk,actor,reason):
    candidate=ShiftHandover.objects.select_related('shift').get(pk=pk);facility_lock(actor,candidate.shift.facility_id)
    obj=ShiftHandover.objects.select_for_update().get(pk=pk)
    if actor.pk!=obj.incoming_id:raise PermissionDenied
    reason_required(reason)
    if not obj.acknowledged_at:obj.acknowledged_at=timezone.now();obj.acknowledgment=reason;obj._history_user=actor;obj.save()
    return obj


@transaction.atomic
def assign_visit(encounter_id,shift_id,actor,reason):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','nurse','clinician','reception')):raise PermissionDenied
    candidate=filter_by_facility(Encounter.objects.all(),actor).get(pk=encounter_id)
    patient=Patient.objects.select_for_update().get(pk=candidate.patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed; reload.')
    facility_lock(actor,candidate.facility_id)
    visit=Encounter.objects.select_for_update().get(pk=encounter_id)
    shift=DutyShift.objects.select_for_update().get(pk=shift_id);now=timezone.now();reason_required(reason)
    if visit.patient_id!=patient.pk or visit.status!='open' or visit.facility_id!=shift.facility_id:raise ValidationError('Choose an open visit and duty in the same facility.')
    staff_at(shift.staff,shift.facility_id,check_employment=True)
    if shift.staff.role!='clinician' or shift.status!='published' or not shift.starts_at<=now<shift.ends_at or shift.availability!='accepting':raise ValidationError('Choose a doctor currently accepting patients.')
    att=Attendance.objects.filter(shift=shift,clock_out__isnull=True).first()
    if not att or att.breaks.filter(ended_at__isnull=True).exists():raise ValidationError('Doctor is not checked in and available.')
    if visit.clinician_id==shift.staff_id:return visit
    if Encounter.objects.filter(clinician=shift.staff,status='open').count()>=shift.capacity:raise ValidationError('Doctor is at configured open-visit capacity.')
    DutyAssignment.objects.create(encounter=visit,shift=shift,previous_clinician=visit.clinician,reason=reason,created_by=actor)
    visit.clinician=shift.staff;visit._history_user=actor;visit.save(update_fields=['clinician']);return visit


@transaction.atomic
def request_swap(actor, first_id, second_id, reason):
    first=DutyShift.objects.get(pk=first_id)
    facility_lock(actor,first.facility_id)
    shifts={s.pk:s for s in DutyShift.objects.select_for_update().filter(pk__in=[first_id,second_id]).order_by('pk')}
    if len(shifts)!=2:raise ValidationError('Choose two different shifts.')
    first,second=shifts[first_id],shifts[second_id]
    if actor.pk!=first.staff_id:manager(actor)
    if first.facility_id!=second.facility_id or first.staff_id==second.staff_id or first.staff.role!=second.staff.role:raise ValidationError('Choose different staff with the same role in this facility.')
    reason_required(reason)
    for shift in (first,second):
        staff_at(shift.staff,first.facility_id,shift.starts_at,shift.ends_at)
        if shift.status!='published' or shift.starts_at<=timezone.now() or Attendance.objects.filter(shift=shift).exists():raise ValidationError('Only future published, unworked shifts can be swapped.')
        if shift.cover_requests.filter(status='requested').exists():raise ValidationError('A cover or swap already awaits review for one of these shifts.')
    a=ShiftCover.objects.create(shift=first,original_staff=first.staff,replacement=second.staff,reason=reason,created_by=actor)
    b=ShiftCover.objects.create(shift=second,original_staff=second.staff,replacement=first.staff,reason=reason,created_by=actor,swap_partner=a)
    a.swap_partner=b;a.save(update_fields=['swap_partner'])
    return a


def review_swap(obj, actor, decision, reason):
    pair=list(ShiftCover.objects.select_for_update().filter(pk__in=[obj.pk,obj.swap_partner_id]).order_by('pk'))
    if len(pair)!=2 or any(x.swap_partner_id not in [p.pk for p in pair] or x.swap_partner_id==x.pk for x in pair):raise ValidationError('Invalid swap pairing; contact an administrator.')
    if all(x.status!='requested' for x in pair):return obj
    if any(x.status!='requested' for x in pair):raise ValidationError('Swap state changed; review both requests.')
    if decision=='accept':
        if actor.pk!=obj.replacement_id:raise PermissionDenied
        obj.accepted_at=timezone.now();obj._history_user=actor;obj.save();return obj
    supervisor(actor,obj.created_by_id);reason_required(reason)
    if actor.pk in {x.original_staff_id for x in pair}:raise ValidationError('A supervisor outside the swap must review both duties.')
    if decision not in ('approved','rejected'):raise ValidationError('Choose approve or reject.')
    if decision=='approved':
        if any(not x.accepted_at for x in pair):raise ValidationError('Both replacement staff must accept before the atomic swap.')
        shifts={s.pk:s for s in DutyShift.objects.select_for_update().filter(pk__in=[x.shift_id for x in pair]).order_by('pk')}
        for item in pair:
            shift=shifts[item.shift_id]
            if shift.facility_id!=obj.shift.facility_id or shift.status!='published' or shift.staff_id!=item.original_staff_id or shift.starts_at<=timezone.now() or Attendance.objects.filter(shift=shift).exists():raise ValidationError('A shift changed or started; reject this stale swap.')
            staff_at(item.replacement,shift.facility_id,shift.starts_at,shift.ends_at)
            if item.replacement.role!=shift.staff.role:raise ValidationError('Duty role changed.')
            if DutyShift.objects.filter(staff=item.replacement,status='published',starts_at__lt=shift.ends_at,ends_at__gt=shift.starts_at).exclude(pk__in=shifts).exists() or StaffLeave.objects.filter(staff=item.replacement,status='approved',starts_at__lt=shift.ends_at,ends_at__gt=shift.starts_at).exists():raise ValidationError('Replacement has a duty or approved leave conflict.')
        if shifts[pair[0].shift_id].starts_at<shifts[pair[1].shift_id].ends_at and shifts[pair[1].shift_id].starts_at<shifts[pair[0].shift_id].ends_at:raise ValidationError('Overlapping duties cannot form a reciprocal swap.')
        for item in pair:
            shift=shifts[item.shift_id];shift.staff=item.replacement;shift.availability='unavailable';shift.revision+=1;shift._history_user=actor;shift.save()
    for item in pair:
        item.status=decision;item.reviewed_by=actor;item.reviewed_at=timezone.now();item.review_reason=reason;item._history_user=actor;item.save()
    return obj


@transaction.atomic
def save_employment(actor, profile_id, *, employment_type, status, starts_on, ends_on, reason, revision=0):
    manager(actor)
    profile=StaffProfile.objects.select_related('user').get(pk=profile_id)
    locked_facility=facility_lock(actor,profile.facility_id)
    profile=StaffProfile.objects.select_for_update().get(pk=profile_id)
    if profile.facility_id!=locked_facility.pk:raise ValidationError('Staff facility changed. Reload before editing employment.')
    if not profile.facility_id:raise ValidationError('Assign a facility before recording employment.')
    obj=StaffEmployment.objects.select_for_update().filter(staff_id=profile.user_id,facility_id=profile.facility_id).first()
    if revision!=(obj.revision if obj else 0):raise ValidationError('Employment changed. Reload before editing.')
    reason_required(reason)
    if employment_type not in dict(StaffEmployment.TYPES) or status not in dict(StaffEmployment.STATUSES):raise ValidationError('Choose a valid employment type and status.')
    if ends_on and ends_on<starts_on:raise ValidationError('Employment end cannot precede its start.')
    if status=='ended' and (not ends_on or ends_on>timezone.localdate()):raise ValidationError('Ended employment requires an end date on or before today.')
    if employment_type=='fixed_term' and not ends_on:raise ValidationError('Fixed-term employment requires an end date.')
    if obj and obj.status=='ended' and status!='ended' and (status!='onboarding' or starts_on<=obj.ends_on):
        raise ValidationError('Re-employment starts with onboarding and a new start date after the previous end date.')
    now=timezone.now()
    current=DutyShift.objects.filter(facility_id=profile.facility_id,ends_at__gt=now,status='published').filter(Q(staff_id=profile.user_id)|Q(supervisor_id=profile.user_id)|Q(backup_id=profile.user_id))
    if status!='active' and (current.exists() or Attendance.objects.filter(staff_id=profile.user_id,clock_out__isnull=True).exists()):
        raise ValidationError('Cancel or reassign future duties, supervision and backup coverage, and close attendance before changing employment eligibility.')
    if status=='active':
        for duty in current:
            if timezone.localdate(duty.starts_at)<starts_on or (ends_on and timezone.localdate(duty.ends_at-timedelta(microseconds=1))>ends_on):
                raise ValidationError('Employment dates must cover every current or future published duty.')
    if not obj:obj=StaffEmployment(staff_id=profile.user_id,facility_id=profile.facility_id,created_by=actor)
    else:obj.revision+=1
    obj.employment_type=employment_type;obj.status=status;obj.starts_on=starts_on;obj.ends_on=ends_on;obj.reason=reason
    obj._history_user=actor;obj.full_clean();obj.save()
    return obj


@transaction.atomic
def record_credential(actor, *, facility, staff, specialty, credential, reference, expires_on, verified_on=None, notes='', supersedes=None):
    manager(actor);facility_lock(actor,facility.pk)
    if not StaffProfile.objects.filter(user=staff,facility=facility).exists():raise ValidationError('Choose staff assigned to this facility.')
    if not credential.strip() or not reference.strip():raise ValidationError('Credential name and reference are required.')
    if verified_on and verified_on>timezone.localdate():raise ValidationError('Verification cannot be dated in the future.')
    if supersedes:
        previous=StaffCredential.objects.select_for_update().get(pk=supersedes.pk)
        if previous.facility_id!=facility.pk or previous.staff_id!=staff.pk or previous.credential.casefold().strip()!=credential.casefold().strip():
            raise ValidationError('A renewal must match the original staff, facility and credential.')
        if StaffCredential.objects.filter(supersedes=previous).exists():raise ValidationError('This credential has already been renewed. Reload its latest record.')
        if not verified_on:raise ValidationError('Verify the renewal before superseding an earlier credential.')
        if expires_on<=previous.expires_on:raise ValidationError('A renewal must extend the previous expiry date.')
        supersedes=previous
    obj=StaffCredential(facility=facility,staff=staff,specialty=specialty,credential=credential.strip(),reference=reference.strip(),expires_on=expires_on,verified_on=verified_on,notes=notes,supersedes=supersedes,created_by=actor)
    obj.full_clean();obj.save();return obj


@transaction.atomic
def save_coverage_rule(actor, *, department, role, minimum_staff, include_on_call, enabled, reason, rule_id=None, revision=0):
    manager(actor);facility_lock(actor,department.facility_id);reason_required(reason)
    if not department.is_active or role not in dict(User.ROLE_CHOICES) or not 1<=minimum_staff<=200:raise ValidationError('Choose an active department, valid duty role and minimum of 1–200 staff.')
    obj=None
    if rule_id:
        obj=DutyCoverageRule.objects.select_for_update().get(pk=rule_id)
        if obj.department_id!=department.pk or obj.role!=role:raise ValidationError('A coverage rule keeps its original department and role.')
        if revision!=obj.revision:raise ValidationError('Coverage rule changed. Reload before editing.')
        obj.revision+=1
    elif DutyCoverageRule.objects.filter(department=department,role=role).exists():raise ValidationError('A rule already exists for this department and role. Edit that rule instead.')
    if not obj:obj=DutyCoverageRule(department=department,role=role,created_by=actor)
    obj.minimum_staff=minimum_staff;obj.include_on_call=include_on_call;obj.enabled=enabled;obj.reason=reason
    obj._history_user=actor;obj.full_clean();obj.save();return obj


def coverage_gaps(department_id, start, end, proposed=(), exclude_ids=()):
    """Sweep all interval boundaries, counting distinct eligible people, not shift rows."""
    rules=list(DutyCoverageRule.objects.filter(department_id=department_id,enabled=True).select_related('department'))
    if not rules:return []
    scheduled=list(DutyShift.objects.filter(department_id=department_id,status='published',starts_at__lt=end,ends_at__gt=start).exclude(pk__in=exclude_ids).select_related('staff'))
    scheduled+=[s for s in proposed if s.department_id==department_id and s.starts_at<end and s.ends_at>start]
    assignments={(p.user_id,p.facility_id) for p in StaffProfile.objects.filter(user_id__in={s.staff_id for s in scheduled})}
    employments={(e.staff_id,e.facility_id):e for e in StaffEmployment.objects.filter(staff_id__in={s.staff_id for s in scheduled})}
    scheduled=[s for s in scheduled if s.staff.is_active and (s.staff_id,s.facility_id) in assignments and employment_allows(employments.get((s.staff_id,s.facility_id)),max(start,s.starts_at),min(end,s.ends_at))]
    boundaries=sorted({start,end}|{max(start,s.starts_at) for s in scheduled}|{min(end,s.ends_at) for s in scheduled})
    gaps=[]
    for rule in rules:
        for left,right in zip(boundaries,boundaries[1:]):
            if left>=right:continue
            count=len({s.staff_id for s in scheduled if s.staff.role==rule.role and s.staff.is_active and s.starts_at<=left and s.ends_at>=right and (rule.include_on_call or not s.on_call)})
            if count<rule.minimum_staff:
                gaps.append({'rule':rule,'starts_at':left,'ends_at':right,'scheduled':count})
                break
    return gaps


def validate_coverage(department_id, start, end, proposed=(), exclude_ids=()):
    gaps=coverage_gaps(department_id,start,end,proposed,exclude_ids)
    if gaps:
        gap=gaps[0];rule=gap['rule']
        raise ValidationError(f"Minimum coverage not met: {rule.department.name} / {dict(User.ROLE_CHOICES).get(rule.role,rule.role)} needs {rule.minimum_staff}, has {gap['scheduled']} at {timezone.localtime(gap['starts_at']):%Y-%m-%d %H:%M}. Publish a complete roster group.")


@transaction.atomic
def publish_roster(actor, shift_revisions, reason=''):
    manager(actor)
    if not shift_revisions or len(shift_revisions)>200:raise ValidationError('Select 1–200 draft duties for one facility.')
    candidates=list(DutyShift.objects.filter(pk__in=shift_revisions))
    if len(candidates)!=len(shift_revisions):raise ValidationError('A selected duty no longer exists. Reload the roster.')
    facilities={s.facility_id for s in candidates}
    if len(facilities)!=1:raise ValidationError('Publish one facility roster at a time.')
    facility_id=facilities.pop();facility_lock(actor,facility_id)
    shifts=list(DutyShift.objects.select_for_update(of=('self',)).filter(pk__in=shift_revisions).select_related('staff','supervisor','backup','department').order_by('starts_at','pk'))
    for shift in shifts:
        if shift.revision!=shift_revisions[shift.pk]:raise ValidationError('A selected duty changed. Reload before publishing.')
        if shift.status!='draft':raise ValidationError('Only draft shifts may be published.')
        if shift.ends_at<=timezone.now():raise ValidationError('Cannot publish a finished shift.')
        if not shift.department.is_active or shift.department.facility_id!=facility_id:raise ValidationError('Choose an active department in this facility.')
        # Match clock() lock order: facility, shifts, then staff. This also serializes cross-facility publishing.
    list(User.objects.select_for_update().filter(pk__in={s.staff_id for s in shifts}).order_by('pk'))
    for index,shift in enumerate(shifts):
        check_conflicts(shift.staff,facility_id,shift.starts_at,shift.ends_at,shift.pk)
        for person in [shift.supervisor]+([shift.backup] if shift.backup_id else []):staff_at(person,facility_id,shift.starts_at,shift.ends_at)
        if any(previous.staff_id==shift.staff_id and previous.starts_at<shift.ends_at and previous.ends_at>shift.starts_at for previous in shifts[:index]):raise ValidationError('Selected draft duties overlap for the same staff member.')
    for department_id in {s.department_id for s in shifts}:
        group=[s for s in shifts if s.department_id==department_id]
        # Check each selected duty interval, without inventing coverage obligations between separate weeks.
        for shift in group:validate_coverage(department_id,shift.starts_at,shift.ends_at,[s for s in group if s.starts_at<shift.ends_at and s.ends_at>shift.starts_at])
    for shift in shifts:
        shift.status='published';shift.revision+=1
        if reason:shift.reason=reason
        shift._history_user=actor;shift.save()
    return shifts


@transaction.atomic
def create_attendance_policy(actor, *, facility, effective_from, grace_minutes, rounding_minutes, rounding_mode, reason):
    manager(actor);facility_lock(actor,facility.pk);reason_required(reason)
    if effective_from<timezone.localdate():raise ValidationError('A new attendance policy cannot be backdated.')
    if not 0<=grace_minutes<=120 or rounding_minutes not in (0,1,5,10,15,30) or rounding_mode not in dict(AttendancePolicy.ROUNDING):raise ValidationError('Choose supported grace and rounding settings.')
    obj=AttendancePolicy(facility=facility,effective_from=effective_from,grace_minutes=grace_minutes,rounding_minutes=rounding_minutes,rounding_mode=rounding_mode,reason=reason,created_by=actor)
    obj.full_clean();obj.save();return obj


def attendance_policy_snapshot(shift):
    policy=AttendancePolicy.objects.filter(facility_id=shift.facility_id,effective_from__lte=timezone.localdate(shift.starts_at)).order_by('-effective_from','-pk').first()
    if not policy:return {}
    return {'id':policy.pk,'effective_from':policy.effective_from.isoformat(),'grace_minutes':policy.grace_minutes,'rounding_minutes':policy.rounding_minutes,'rounding_mode':policy.rounding_mode}
