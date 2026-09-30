import csv
from datetime import datetime, timedelta
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.accounts.models import User, Facility, Department, StaffProfile
from apps.encounters.models import Encounter
from common.facility_scope import filter_by_facility, user_staff_facility_id
from .models import DutyShift, Attendance, AttendanceCorrection, StaffCredential, StaffLeave, ShiftCover, ShiftHandover
from . import workforce_services as services


def is_manager(user):return user.is_superuser or user.role in ('admin','manager')

def staff_choices(user):
    return filter_by_facility(User.objects.filter(is_active=True),user,field='staff_profile__facility_id').order_by('username')


def protected(qs,user,staff_field='staff'):
    return qs if is_manager(user) else qs.filter(**{staff_field:user})


def datetime_field(**kwargs):
    return forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'),**kwargs)


def context(request,**extra):return {'workforce_manager':is_manager(request.user),'workforce_timezone':settings.TIME_ZONE,**extra}


@login_required
def board(request):
    if not request.user.is_active:raise PermissionDenied
    now=timezone.now()
    try:day=datetime.strptime(request.GET.get('date',''),'%Y-%m-%d').date()
    except ValueError:day=timezone.localdate()
    start=timezone.make_aware(datetime.combine(day,datetime.min.time()));end=start+timedelta(days=1)
    qs=filter_by_facility(DutyShift.objects.all(),request.user).filter(starts_at__lt=end,ends_at__gt=start).select_related('staff','department','facility','supervisor','attendance').order_by('starts_at','pk')
    if not is_manager(request.user):qs=qs.exclude(status='draft')
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
    return render(request,'operations/workforce_board.html',context(request,page=page,day=day,now=now,gaps=gaps,handovers=handovers.select_related('shift__staff','incoming').order_by('due_at')[:20]))


@login_required
def directory(request):
    services.manager(request.user)
    staff=filter_by_facility(StaffProfile.objects.select_related('user','facility','department'),request.user)
    q=request.GET.get('q','').strip()[:100]
    if q:staff=staff.filter(Q(user__username__icontains=q)|Q(user__first_name__icontains=q)|Q(user__last_name__icontains=q)|Q(title__icontains=q))
    page=Paginator(staff.order_by('user__username'),30).get_page(request.GET.get('page'))
    expiring=filter_by_facility(StaffCredential.objects.filter(expires_on__lte=timezone.localdate()+timedelta(days=60)),request.user).select_related('staff').order_by('expires_on')[:50]
    return render(request,'operations/workforce_directory.html',context(request,page=page,q=q,expiring=expiring))


@login_required
def create(request,kind,pk=None):
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
            repeat_weeks=forms.IntegerField(min_value=1,max_value=12,initial=1,help_text='Create weekly drafts. Review and publish each shift separately.')
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
                fields=['facility','staff','specialty','credential','reference','expires_on','verified_on','notes']
                widgets={'expires_on':forms.DateInput(attrs={'type':'date'}),'verified_on':forms.DateInput(attrs={'type':'date'})}
        title='Record staff credential review'
    else:
        raise PermissionDenied
    form=Form(request.POST or None)
    if kind=='credential':
        form.fields['staff'].queryset=choices
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
            elif kind=='credential':
                with transaction.atomic():
                    services.facility_lock(request.user,data['facility'].pk);services.staff_at(data['staff'],data['facility'].pk)
                    if data['verified_on'] and data['verified_on']>timezone.localdate():raise ValidationError('Verification cannot be dated in the future.')
                    obj=form.save(commit=False);obj.created_by=request.user;obj.save()
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A competing request changed this record; reload before retrying.')
        else:
            messages.success(request,'Recorded. Review any required approvals in the workforce inbox.')
            return redirect('suite-workforce' if kind=='shift' else 'suite-workforce-directory' if kind=='credential' else 'suite-workforce-inbox')
    return render(request,'operations/workflow_form.html',{'form':form,'title':title,'help':f'Dates and times use {settings.TIME_ZONE}. Records retain their audit history.'})


@login_required
def shift_detail(request,pk):
    shift=get_object_or_404(filter_by_facility(DutyShift.objects.select_related('staff','department','supervisor','backup'),request.user),pk=pk)
    if shift.status=='draft' and not is_manager(request.user) and shift.staff_id!=request.user.pk:raise PermissionDenied
    return render(request,'operations/workforce_shift.html',context(request,shift=shift,attendance=getattr(shift,'attendance',None)))


@login_required
def inbox(request):
    leave=protected(filter_by_facility(StaffLeave.objects.all(),request.user),request.user).select_related('staff').order_by('-created_at')[:50]
    covers=filter_by_facility(ShiftCover.objects.all(),request.user,field='shift__facility_id')
    if not is_manager(request.user):covers=covers.filter(Q(created_by=request.user)|Q(original_staff=request.user)|Q(replacement=request.user))
    corrections=filter_by_facility(AttendanceCorrection.objects.all(),request.user,field='attendance__shift__facility_id')
    if not is_manager(request.user):corrections=corrections.filter(attendance__staff=request.user)
    handovers=filter_by_facility(ShiftHandover.objects.all(),request.user,field='shift__facility_id')
    if not is_manager(request.user):handovers=handovers.filter(Q(incoming=request.user)|Q(created_by=request.user))
    return render(request,'operations/workforce_inbox.html',context(request,leave=leave,covers=covers.select_related('shift','original_staff','replacement').order_by('-created_at')[:50],corrections=corrections.select_related('attendance__staff').order_by('-created_at')[:50],handovers=handovers.select_related('shift__staff','incoming').order_by('-created_at')[:50]))


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
    qs=protected(filter_by_facility(Attendance.objects.select_related('shift__department','staff','reviewed_by'),request.user,field='shift__facility_id'),request.user).order_by('-clock_in')
    try:days=max(1,min(90,int(request.GET.get('days','30'))))
    except ValueError:days=30
    qs=qs.filter(clock_in__gte=timezone.now()-timedelta(days=days))
    if request.GET.get('export')=='csv':
        services.manager(request.user)
        response=HttpResponse(content_type='text/csv');response['Content-Disposition']='attachment; filename="approved-attendance.csv"'
        writer=csv.writer(response);writer.writerow(['Attendance','Staff ID','Shift ID','Start ISO','End ISO','Break minutes','Worked minutes','Late minutes','Beyond scheduled end minutes','Reviewer ID'])
        for a in qs.filter(reviewed_at__isnull=False).exclude(corrections__status='requested').iterator():
            t=services.attendance_totals(a)
            writer.writerow([a.pk,a.staff_id,a.shift_id,t['start'].isoformat(),t['end'].isoformat() if t['end'] else '',t['break_minutes'],t['worked_minutes'],t['late_minutes'],t['overtime_minutes'],a.reviewed_by_id])
        return response
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    for a in page:a.totals=services.attendance_totals(a)
    return render(request,'operations/workforce_timesheets.html',context(request,page=page,days=days))


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
