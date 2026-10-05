import csv
from datetime import datetime, timedelta
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.accounts.models import User, Facility, Department, StaffProfile
from apps.accounts.approval_services import workforce_allowed
from apps.encounters.models import Encounter
from common.facility_scope import filter_by_facility, user_staff_facility_id
from .models import DutyShift, Attendance, AttendanceCorrection, StaffCredential, StaffLeave, ShiftCover, ShiftHandover, StaffEmployment, DutyCoverageRule, AttendancePolicy
from . import workforce_services as services


def is_manager(user):return user.is_superuser or user.role in ('admin','manager')

def staff_choices(user):
    return filter_by_facility(User.objects.filter(is_active=True),user,field='staff_profile__facility_id').order_by('username')


def protected(qs,user,staff_field='staff'):
    return qs if is_manager(user) else qs.filter(**{staff_field:user})


def datetime_field(**kwargs):
    return forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'),**kwargs)


def capability(user, operation):
    # The grant helper checks the real staff assignment as well as selected scope.
    # Do not make delegated reviewers managers of unrelated workforce records.
    return is_manager(user) or workforce_allowed(user,user_staff_facility_id(user),operation)


def review_allowed(request, facility_id, operation, excluded_ids):
    """Memoize read-only authority for this request, never a later form POST."""
    if request.user.pk in excluded_ids:return False
    cache=request.__dict__.setdefault('_workforce_review_authority',{})
    key=(facility_id,operation)
    if key not in cache:
        cache[key]=services.can_review(request.user,facility_id,operation,set())
    return cache[key]


def context(request,**extra):
    return {'workforce_manager':is_manager(request.user),'workforce_can_publish':capability(request.user,'roster_publish'),'workforce_timezone':settings.TIME_ZONE,**extra}


@login_required
def board(request):
    if not request.user.is_active:raise PermissionDenied
    now=timezone.now()
    try:day=datetime.strptime(request.GET.get('date',''),'%Y-%m-%d').date()
    except ValueError:day=timezone.localdate()
    start=timezone.make_aware(datetime.combine(day,datetime.min.time()));end=start+timedelta(days=1)
    qs=filter_by_facility(DutyShift.objects.all(),request.user).filter(starts_at__lt=end,ends_at__gt=start).select_related('staff','department','facility','supervisor','attendance').order_by('starts_at','pk')
    if not capability(request.user,'roster_publish'):qs=qs.exclude(status='draft')
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    for shift in page:
        att=getattr(shift,'attendance',None)
        shift.workload=Encounter.objects.filter(clinician_id=shift.staff_id,status='open').count()
        shift.presence='Scheduled'
        if shift.status=='cancelled':shift.presence='Cancelled'
        elif att and att.clock_out:shift.presence='Clocked out'
        elif att and att.breaks.filter(ended_at__isnull=True).exists():shift.presence='On break'
        elif att:shift.presence='Checked in'
        elif shift.starts_at<=now:shift.presence='No check-in recorded'
        if att:shift.totals=services.attendance_totals(att,now)
    handovers=filter_by_facility(ShiftHandover.objects.filter(acknowledged_at__isnull=True),request.user,field='shift__facility_id')
    if not is_manager(request.user):handovers=handovers.filter(Q(incoming=request.user)|Q(created_by=request.user))
    gaps=[]
    if is_manager(request.user):
        for dept in filter_by_facility(Department.objects.filter(is_active=True),request.user):
            current=DutyShift.objects.filter(department=dept,status='published',starts_at__lte=now,ends_at__gt=now)
            checked=current.filter(attendance__clock_out__isnull=True,attendance__clock_in__isnull=False)
            if not checked.exists():gaps.append(dept)
    coverage=[]
    coverage_rules=[]
    if is_manager(request.user):
        coverage_rules=filter_by_facility(DutyCoverageRule.objects.select_related('department'),request.user,field='department__facility_id').order_by('department__name','role')
        for department_id in {r.department_id for r in coverage_rules if r.enabled}:
            coverage.extend(services.coverage_gaps(department_id,now,now+timedelta(seconds=1)))
    return render(request,'operations/workforce_board.html',context(request,page=page,day=day,now=now,gaps=gaps,coverage=coverage,coverage_rules=coverage_rules,handovers=handovers.select_related('shift__staff','incoming').order_by('due_at')[:20]))


@login_required
def directory(request):
    services.manager(request.user)
    staff=filter_by_facility(StaffProfile.objects.select_related('user','facility','department'),request.user)
    q=request.GET.get('q','').strip()[:100]
    if q:staff=staff.filter(Q(user__username__icontains=q)|Q(user__first_name__icontains=q)|Q(user__last_name__icontains=q)|Q(title__icontains=q))
    page=Paginator(staff.order_by('user__username'),30).get_page(request.GET.get('page'))
    employment={(e.staff_id,e.facility_id):e for e in filter_by_facility(StaffEmployment.objects.filter(staff_id__in=[p.user_id for p in page]),request.user)}
    for profile in page:profile.employment=employment.get((profile.user_id,profile.facility_id))
    credentials=filter_by_facility(StaffCredential.objects.all(),request.user).select_related('staff','supersedes').order_by('-created_at')[:100]
    expiring=filter_by_facility(StaffCredential.objects.filter(renewal__isnull=True,expires_on__lte=timezone.localdate()+timedelta(days=60)),request.user).select_related('staff').order_by('expires_on')[:50]
    return render(request,'operations/workforce_directory.html',context(request,page=page,q=q,expiring=expiring,credentials=credentials))


@login_required
def create(request,kind,pk=None):
    if kind in ('employment','coverage','publish','attendance-policy'):
        return settings_form(request,kind,pk)
    choices=staff_choices(request.user)
    shift=None;attendance=None
    if pk is not None:
        if kind=='correction':
            attendance=get_object_or_404(protected(filter_by_facility(Attendance.objects.select_related('shift'),request.user,field='shift__facility_id'),request.user),pk=pk)
        else:
            shift=get_object_or_404(filter_by_facility(DutyShift.objects.all(),request.user),pk=pk)
            if request.user.pk!=shift.staff_id and (not is_manager(request.user) or kind=='handover'):raise PermissionDenied
            choices=choices.filter(staff_profile__facility_id=shift.facility_id)
    if kind=='swap':
        published=filter_by_facility(DutyShift.objects.filter(status='published',starts_at__gt=timezone.now()),request.user).select_related('staff','department')
        own=published if is_manager(request.user) else published.filter(staff=request.user)
        class Form(forms.Form):
            first_id=forms.ModelChoiceField(queryset=own,label='First duty')
            second_id=forms.ModelChoiceField(queryset=published,label='Reciprocal duty')
            reason=forms.CharField(max_length=250)
        title='Request an atomic reciprocal swap'
    elif kind=='shift':
        services.manager(request.user)
        class Form(forms.Form):
            facility=forms.ModelChoiceField(queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk'))
            department=forms.ModelChoiceField(queryset=filter_by_facility(Department.objects.filter(is_active=True),request.user))
            staff=forms.ModelChoiceField(queryset=choices)
            supervisor=forms.ModelChoiceField(queryset=choices)
            backup=forms.ModelChoiceField(queryset=choices,required=False)
            starts_at=datetime_field()
            ends_at=datetime_field()
            on_call=forms.BooleanField(required=False)
            capacity=forms.IntegerField(min_value=1,max_value=200,initial=10,help_text='Maximum open consultations; checked on duty-board assignments.')
            repeat_weeks=forms.IntegerField(min_value=1,max_value=12,initial=1,help_text='Create weekly drafts, then publish a complete group or an individual shift.')
            reason=forms.CharField(max_length=250,required=False)
        title='Create duty roster'
    elif kind=='leave':
        class Form(forms.Form):
            starts_at=datetime_field()
            ends_at=datetime_field()
            reason=forms.CharField(max_length=250)
        title='Request leave'
    elif kind=='cover' and shift:
        class Form(forms.Form):
            replacement=forms.ModelChoiceField(queryset=choices.exclude(pk=shift.staff_id).filter(role=shift.staff.role))
            reason=forms.CharField(max_length=250)
        title='Request shift cover'
    elif kind=='handover' and shift:
        class Form(forms.Form):
            incoming=forms.ModelChoiceField(queryset=choices.exclude(pk=shift.staff_id).filter(role=shift.staff.role))
            summary=forms.CharField(widget=forms.Textarea,help_text='Operational summary only; keep clinical/HR details in restricted records. List outstanding task references and responsible owners.')
            due_at=datetime_field()
        title='Record shift handover'
    elif kind=='correction' and attendance:
        class Form(forms.Form):
            clock_in=datetime_field()
            clock_out=datetime_field()
            break_minutes=forms.IntegerField(min_value=0)
            reason=forms.CharField(max_length=250)
        title='Request attendance correction'
    elif kind=='credential':
        services.manager(request.user)
        class Form(forms.ModelForm):
            class Meta:
                model=StaffCredential
                fields=['facility','staff','specialty','credential','reference','expires_on','verified_on','notes','supersedes']
                widgets={'expires_on':forms.DateInput(attrs={'type':'date'}),'verified_on':forms.DateInput(attrs={'type':'date'})}
        title='Record staff credential review'
    else:
        raise PermissionDenied
    form=Form(request.POST or None)
    if kind=='credential':
        form.fields['supersedes'].queryset=filter_by_facility(StaffCredential.objects.filter(renewal__isnull=True),request.user).select_related('staff')
        form.fields['supersedes'].label='Renewal of existing credential (optional)'
        form.fields['staff'].queryset=filter_by_facility(User.objects.all(),request.user,field='staff_profile__facility_id').order_by('username')
        form.fields['facility'].queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk')
    if request.method=='POST' and form.is_valid():
        try:
            data=form.cleaned_data
            if kind=='swap':services.request_swap(request.user,data['first_id'].pk,data['second_id'].pk,data['reason'])
            elif kind=='shift':services.create_shift(request.user,**data)
            elif kind=='leave':services.request_leave(request.user,**data)
            elif kind=='cover':services.request_cover(pk,request.user,**data)
            elif kind=='handover':services.handover(pk,request.user,**data)
            elif kind=='correction':services.request_correction(pk,request.user,**data)
            elif kind=='credential':services.record_credential(request.user,**data)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A competing request changed this record; reload before retrying.')
        else:
            messages.success(request,'Recorded. Review any required approvals in the workforce inbox.')
            return redirect('suite-workforce' if kind=='shift' else 'suite-workforce-directory' if kind=='credential' else 'suite-workforce-inbox')
    return render(request,'operations/workflow_form.html',{'form':form,'title':title,'help':f'Dates and times use {settings.TIME_ZONE}. Records retain their audit history.'})


@login_required
def shift_detail(request,pk):
    shift=get_object_or_404(filter_by_facility(DutyShift.objects.select_related('staff','department','supervisor','backup'),request.user),pk=pk)
    if shift.status=='draft' and not workforce_allowed(request.user,shift.facility_id,'roster_publish') and shift.staff_id!=request.user.pk:raise PermissionDenied
    shift.can_publish=shift.status=='draft' and workforce_allowed(request.user,shift.facility_id,'roster_publish')
    return render(request,'operations/workforce_shift.html',context(request,shift=shift,attendance=getattr(shift,'attendance',None)))


@login_required
def inbox(request):
    leave=filter_by_facility(StaffLeave.objects.all(),request.user)
    if not capability(request.user,'leave_review'):leave=leave.filter(staff=request.user)
    leave=list(leave.select_related('staff').order_by('-created_at')[:50])
    for record in leave:
        record.can_review=review_allowed(request,record.facility_id,'leave_review',{record.staff_id,record.created_by_id})
    covers=filter_by_facility(ShiftCover.objects.all(),request.user,field='shift__facility_id')
    if not capability(request.user,'cover_review'):
        covers=covers.filter(Q(created_by=request.user)|Q(original_staff=request.user)|Q(replacement=request.user)|Q(swap_partner__created_by=request.user)|Q(swap_partner__original_staff=request.user)|Q(swap_partner__replacement=request.user))
    covers=list(covers.select_related('shift','original_staff','replacement','swap_partner').order_by('-created_at')[:50])
    for record in covers:
        record.can_review=review_allowed(request,record.shift.facility_id,'cover_review',services.cover_review_excluded(record))
    corrections=filter_by_facility(AttendanceCorrection.objects.all(),request.user,field='attendance__shift__facility_id')
    if not capability(request.user,'attendance_review'):corrections=corrections.filter(Q(attendance__staff=request.user)|Q(created_by=request.user))
    corrections=list(corrections.select_related('attendance__staff','attendance__shift').order_by('-created_at')[:50])
    for record in corrections:
        record.can_review=review_allowed(request,record.attendance.shift.facility_id,'attendance_review',{record.attendance.staff_id,record.created_by_id})
    handovers=filter_by_facility(ShiftHandover.objects.all(),request.user,field='shift__facility_id')
    if not is_manager(request.user):handovers=handovers.filter(Q(incoming=request.user)|Q(created_by=request.user))
    return render(request,'operations/workforce_inbox.html',context(request,leave=leave,covers=covers,corrections=corrections,handovers=handovers.select_related('shift__staff','incoming').order_by('-created_at')[:50]))


@login_required
def action(request,kind,pk):
    if request.method!='POST':return HttpResponse('Use POST.',status=405)
    reason=request.POST.get('reason','')[:250];decision=request.POST.get('decision','')
    scope={'shift':(DutyShift,'facility_id'),'clock':(DutyShift,'facility_id'),'leave':(StaffLeave,'facility_id'),'cover':(ShiftCover,'shift__facility_id'),'correction':(AttendanceCorrection,'attendance__shift__facility_id'),'timesheet':(Attendance,'shift__facility_id'),'handover':(ShiftHandover,'shift__facility_id')}
    if kind not in scope:raise PermissionDenied
    model,field=scope[kind];get_object_or_404(filter_by_facility(model.objects.all(),request.user,field=field),pk=pk)
    try:
        if kind=='shift':
            try:revision=int(request.POST.get('revision',''))
            except ValueError:raise ValidationError('Reload the current shift.')
            services.shift_action(pk,request.user,decision,revision,reason)
        elif kind=='clock':services.clock(pk,request.user,decision)
        elif kind=='leave':services.review_leave(pk,request.user,decision,reason)
        elif kind=='cover':services.review_cover(pk,request.user,decision,reason)
        elif kind=='correction':services.review_correction(pk,request.user,decision,reason)
        elif kind=='timesheet':services.approve_timesheet(pk,request.user,reason)
        elif kind=='handover':services.acknowledge_handover(pk,request.user,reason)
    except (ValidationError,IntegrityError) as exc:messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Record changed. Reload before retrying.')
    else:messages.success(request,'Action recorded.')
    if kind in ('shift','clock'):return redirect('suite-workforce-shift',pk=pk)
    return redirect('suite-workforce-timesheets' if kind=='timesheet' else 'suite-workforce-inbox')


@login_required
def timesheets(request):
    qs=filter_by_facility(Attendance.objects.select_related('shift__department','staff','reviewed_by'),request.user,field='shift__facility_id').order_by('-clock_in')
    if not capability(request.user,'attendance_review'):qs=qs.filter(staff=request.user)
    try:days=max(1,min(90,int(request.GET.get('days','30'))))
    except ValueError:days=30
    qs=qs.filter(clock_in__gte=timezone.now()-timedelta(days=days))
    if request.GET.get('export')=='csv':
        services.manager(request.user)
        response=HttpResponse(content_type='text/csv');response['Content-Disposition']='attachment; filename="approved-attendance.csv"'
        writer=csv.writer(response);writer.writerow(['Attendance','Staff ID','Shift ID','Start ISO','End ISO','Break minutes','Worked minutes','Late minutes','Beyond scheduled end minutes','Reviewer ID','Policy ID','Policy worked minutes','Policy late minutes','Grace minutes','Rounding minutes','Rounding mode'])
        for a in qs.filter(reviewed_at__isnull=False).exclude(corrections__status='requested').iterator():
            t=services.attendance_totals(a)
            writer.writerow([a.pk,a.staff_id,a.shift_id,t['start'].isoformat(),t['end'].isoformat() if t['end'] else '',t['break_minutes'],t['worked_minutes'],t['late_minutes'],t['overtime_minutes'],a.reviewed_by_id,t['policy'].get('id',''),t['policy_worked_minutes'],t['policy_late_minutes'],t['policy'].get('grace_minutes',0),t['policy'].get('rounding_minutes',0),t['policy'].get('rounding_mode','exact')])
        return response
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    for a in page:
        a.totals=services.attendance_totals(a)
        a.can_review=review_allowed(request,a.shift.facility_id,'attendance_review',{a.staff_id,a.created_by_id}) and bool(a.clock_out) and not a.corrections.filter(status='requested').exists()
        a.can_request_correction=is_manager(request.user) or a.staff_id==request.user.pk
    policies=filter_by_facility(AttendancePolicy.objects.select_related('facility'),request.user).order_by('-effective_from')[:30] if is_manager(request.user) else []
    return render(request,'operations/workforce_timesheets.html',context(request,page=page,days=days,policies=policies))


@login_required
def assign(request):
    if not request.user.is_active or not (request.user.is_superuser or request.user.role in ('admin','clinician','nurse','reception')):raise PermissionDenied
    class Form(forms.Form):
        encounter=forms.ModelChoiceField(queryset=filter_by_facility(Encounter.objects.filter(status='open'),request.user).select_related('patient').order_by('-pk'))
        shift=forms.ModelChoiceField(queryset=filter_by_facility(DutyShift.objects.filter(status='published',staff__role='clinician',starts_at__lte=timezone.now(),ends_at__gt=timezone.now(),availability='accepting'),request.user).select_related('staff','department'))
        reason=forms.CharField(max_length=250)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:services.assign_visit(form.cleaned_data['encounter'].pk,form.cleaned_data['shift'].pk,request.user,form.cleaned_data['reason'])
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:messages.success(request,'Doctor assigned; prior assignment retained in history.');return redirect('suite-workforce')
    return render(request,'operations/workflow_form.html',{'form':form,'title':'Assign an on-duty doctor','help':'Only a checked-in doctor currently accepting patients can receive work here. Changing assignment requires a recorded reason.'})


def settings_form(request, kind, pk=None):
    """Publication may be delegated; workforce setup remains manager-only."""
    if kind=='publish':
        if not capability(request.user,'roster_publish'):raise PermissionDenied
    else:services.manager(request.user)
    initial={};obj=None
    facilities=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk')
    departments=filter_by_facility(Department.objects.filter(is_active=True),request.user)
    if kind=='employment':
        profile=get_object_or_404(filter_by_facility(StaffProfile.objects.select_related('user'),request.user),pk=pk)
        obj=StaffEmployment.objects.filter(staff=profile.user,facility_id=profile.facility_id).first()
        class Form(forms.Form):
            employment_type=forms.ChoiceField(choices=StaffEmployment.TYPES)
            status=forms.ChoiceField(choices=StaffEmployment.STATUSES)
            starts_on=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
            ends_on=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}),help_text='Last eligible date, inclusive. Required for fixed-term or ended employment.')
            reason=forms.CharField(max_length=250)
            revision=forms.IntegerField(widget=forms.HiddenInput)
        if obj:initial={name:getattr(obj,name) for name in ('employment_type','status','starts_on','ends_on','revision')}
        else:initial={'revision':0,'status':'onboarding'}
        title=f'Employment · {profile.user}'
        help_text='Employment eligibility is separate from login access and role permissions. Unrecorded legacy staff remain eligible. Cancel or reassign published duties and close attendance before suspending or ending employment.'
    elif kind=='coverage':
        if pk:obj=get_object_or_404(filter_by_facility(DutyCoverageRule.objects.all(),request.user,field='department__facility_id'),pk=pk)
        class Form(forms.Form):
            department=forms.ModelChoiceField(queryset=departments)
            role=forms.ChoiceField(choices=User.ROLE_CHOICES)
            minimum_staff=forms.IntegerField(min_value=1,max_value=200,initial=1)
            include_on_call=forms.BooleanField(required=False)
            enabled=forms.BooleanField(required=False,initial=True)
            reason=forms.CharField(max_length=250)
            revision=forms.IntegerField(widget=forms.HiddenInput)
        initial={'revision':0}
        if obj:initial={name:getattr(obj,name) for name in ('department','role','minimum_staff','include_on_call','enabled','revision')}
        title='Department minimum duty coverage'
        help_text='Configured minima apply throughout each duty interval being published or cancelled. They count distinct rostered people, not checked-in attendance. New rules do not change existing duties. No staffing or legal standard is assumed.'
    elif kind=='attendance-policy':
        class Form(forms.Form):
            facility=forms.ModelChoiceField(queryset=facilities)
            effective_from=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}),initial=timezone.localdate)
            grace_minutes=forms.IntegerField(min_value=0,max_value=120,initial=0,help_text='Subtract this allowance from exact lateness, to a minimum of zero.')
            rounding_minutes=forms.TypedChoiceField(choices=[(0,'Exact worked minutes')]+[(n,f'{n} minute(s)') for n in (1,5,10,15,30)],coerce=int,initial=0)
            rounding_mode=forms.ChoiceField(choices=AttendancePolicy.ROUNDING)
            reason=forms.CharField(max_length=250)
        title='Add attendance policy'
        help_text='Applies to new clock-ins for shifts starting on or after the effective date. Each attendance keeps its policy snapshot. Original events, exact totals and existing attendance remain unchanged. Rounding applies only to total net worked minutes and does not authorize overtime or payroll.'
    elif kind=='publish':
        drafts=filter_by_facility(DutyShift.objects.filter(status='draft',ends_at__gt=timezone.now()),request.user).select_related('staff','department').order_by('starts_at','pk')
        class Form(forms.Form):
            duties=forms.ModelMultipleChoiceField(queryset=drafts,widget=forms.CheckboxSelectMultiple)
            snapshot=forms.CharField(widget=forms.HiddenInput)
            reason=forms.CharField(max_length=250,required=False)
        snapshot={str(s.pk):s.revision for s in drafts[:200]}
        # Bound both the review list and its revision snapshot to the same set.
        Form.base_fields['duties'].queryset=drafts.filter(pk__in=snapshot)
        initial={'snapshot':signing.dumps({'actor':request.user.pk,'revisions':snapshot},salt='workforce-roster')}
        title='Publish a roster group'
        help_text='Select up to 200 duties from one facility. Every conflict, leave, employment and minimum-coverage check must pass before any selected duty is published. Refresh if the roster changed.'
    else:raise PermissionDenied
    form=Form(request.POST or None,initial=initial)
    if kind=='coverage' and obj:
        form.fields['department'].disabled=True;form.fields['role'].disabled=True
    if request.method=='POST' and form.is_valid():
        try:
            data=form.cleaned_data
            if kind=='employment':services.save_employment(request.user,profile.pk,**data)
            elif kind=='coverage':services.save_coverage_rule(request.user,rule_id=obj.pk if obj else None,**data)
            elif kind=='attendance-policy':services.create_attendance_policy(request.user,**data)
            else:
                try:
                    signed=signing.loads(data['snapshot'],salt='workforce-roster',max_age=3600)
                    if signed['actor']!=request.user.pk:raise signing.BadSignature
                    revisions={d.pk:signed['revisions'][str(d.pk)] for d in data['duties']}
                except (signing.BadSignature,KeyError,TypeError):raise ValidationError('Roster review expired or changed. Reload before publishing.')
                services.publish_roster(request.user,revisions,data['reason'])
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A competing request changed this record. Reload before retrying.')
        else:
            messages.success(request,'Workforce changes recorded.')
            return redirect('suite-workforce-directory' if kind=='employment' else 'suite-workforce-timesheets' if kind=='attendance-policy' else 'suite-workforce')
    return render(request,'operations/workflow_form.html',{'form':form,'title':title,'help':help_text})
