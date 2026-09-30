"""Workforce mutations serialize per facility; events retain their original times."""
from datetime import timedelta
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
                     StaffLeave, ShiftCover, ShiftHandover, DutyAssignment, StaffCredential)


def manager(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','manager')):
        raise PermissionDenied


def facility_lock(actor, facility_id):
    if not actor.is_active:raise PermissionDenied
    facility=filter_by_facility(Facility.objects.select_for_update(),actor,field='pk').filter(pk=facility_id,is_active=True).first()
    if not facility:raise PermissionDenied
    return facility


def staff_at(staff,facility_id):
    if not staff.is_active or not StaffProfile.objects.filter(user=staff,facility_id=facility_id).exists():
        raise ValidationError('Choose active staff assigned to this facility.')


def interval(start,end):
    if not timezone.is_aware(start) or not timezone.is_aware(end) or end<=start:
        raise ValidationError('End must be after start; use facility-local dates and times.')


def reason_required(reason):
    if not reason.strip():raise ValidationError('A reason is required.')


def check_conflicts(staff,facility_id,start,end,exclude=None):
    staff_at(staff,facility_id)
    if DutyShift.objects.filter(staff=staff,status='published',starts_at__lt=end,ends_at__gt=start).exclude(pk=exclude).exists():
        raise ValidationError('This staff member already has an overlapping published duty.')
    if StaffLeave.objects.filter(staff=staff,status='approved',starts_at__lt=end,ends_at__gt=start).exists():
        raise ValidationError('This duty overlaps approved leave.')


@transaction.atomic
def create_shift(actor,facility,department,staff,supervisor,starts_at,ends_at,backup=None,on_call=False,capacity=10,repeat_weeks=1,reason=''):
    manager(actor);facility_lock(actor,facility.pk)
    interval(starts_at,ends_at)
    if department.facility_id!=facility.pk or not department.is_active:raise ValidationError('Choose an active department in this facility.')
    for user in [staff,supervisor]+([backup] if backup else []):staff_at(user,facility.pk)
    if backup and backup.pk==staff.pk:raise ValidationError('Backup must be another staff member.')
    if not 1<=capacity<=200 or not 1<=repeat_weeks<=12:raise ValidationError('Capacity must be 1–200 and recurrence 1–12 weeks.')
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
            if shift.status!='draft':raise ValidationError('Only draft shifts may be published.')
            if shift.ends_at<=timezone.now():raise ValidationError('Cannot publish a finished shift.')
            check_conflicts(shift.staff,shift.facility_id,shift.starts_at,shift.ends_at,shift.pk)
            for person in [shift.supervisor]+([shift.backup] if shift.backup_id else []):staff_at(person,shift.facility_id)
            shift.status='published'
        else:
            reason_required(reason)
            if Attendance.objects.filter(shift=shift).exists():raise ValidationError('A recorded attendance cannot be cancelled. Close and review attendance instead.')
            if shift.status=='cancelled':return shift
            shift.status='cancelled';shift.availability='unavailable';shift.reason=reason
    elif action in ('accepting','unavailable'):
        if actor.pk!=shift.staff_id:raise PermissionDenied
        if shift.status!='published' or not shift.starts_at<=timezone.now()<shift.ends_at:raise ValidationError('Only a current published duty can accept patients.')
        attendance=Attendance.objects.filter(shift=shift,clock_out__isnull=True).first()
        if action=='accepting' and (not attendance or attendance.breaks.filter(ended_at__isnull=True).exists()):raise ValidationError('Clock in and end any break before accepting patients.')
        shift.availability=action
    else:raise ValidationError('Unknown shift action.')
    shift.revision+=1;shift._history_user=actor;shift.save();return shift


@transaction.atomic
def clock(pk,actor,action):
    candidate=DutyShift.objects.get(pk=pk);facility_lock(actor,candidate.facility_id)
    shift=DutyShift.objects.select_for_update().get(pk=pk)
    if actor.pk!=shift.staff_id:raise PermissionDenied
    staff_at(actor,shift.facility_id)
    now=timezone.now();attendance=Attendance.objects.filter(shift=shift).first()
    if action=='in':
        if attendance:return attendance
        if shift.status!='published' or not shift.starts_at<=now<shift.ends_at:raise ValidationError('Clock-in requires a current published shift.')
        # User lock also serializes attendance across facility transfers.
        User.objects.select_for_update().get(pk=actor.pk)
        if Attendance.objects.filter(staff=actor,clock_out__isnull=True).exists():raise ValidationError('Close your previous attendance first.')
        attendance=Attendance.objects.create(shift=shift,staff=actor,clock_in=now,created_by=actor)
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
    return {'start':start,'end':end if attendance.clock_out or correction else None,'break_minutes':round(break_minutes,1),'worked_minutes':round(worked,1),'late_minutes':round(max(0,(start-attendance.shift.starts_at).total_seconds()/60),1),'overtime_minutes':round(max(0,(end-attendance.shift.ends_at).total_seconds()/60),1),'corrected':bool(correction)}


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
    staff_at(replacement,shift.facility_id);reason_required(reason)
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
    staff_at(incoming,shift.facility_id);reason_required(summary)
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
    staff_at(shift.staff,shift.facility_id)
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
        staff_at(shift.staff,first.facility_id)
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
            staff_at(item.replacement,shift.facility_id)
            if item.replacement.role!=shift.staff.role:raise ValidationError('Duty role changed.')
            if DutyShift.objects.filter(staff=item.replacement,status='published',starts_at__lt=shift.ends_at,ends_at__gt=shift.starts_at).exclude(pk__in=shifts).exists() or StaffLeave.objects.filter(staff=item.replacement,status='approved',starts_at__lt=shift.ends_at,ends_at__gt=shift.starts_at).exists():raise ValidationError('Replacement has a duty or approved leave conflict.')
        if shifts[pair[0].shift_id].starts_at<shifts[pair[1].shift_id].ends_at and shifts[pair[1].shift_id].starts_at<shifts[pair[0].shift_id].ends_at:raise ValidationError('Overlapping duties cannot form a reciprocal swap.')
        for item in pair:
            shift=shifts[item.shift_id];shift.staff=item.replacement;shift.availability='unavailable';shift.revision+=1;shift._history_user=actor;shift.save()
    for item in pair:
        item.status=decision;item.reviewed_by=actor;item.reviewed_at=timezone.now();item.review_reason=reason;item._history_user=actor;item.save()
    return obj
