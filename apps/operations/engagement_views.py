from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from apps.appointments.models import Appointment
from apps.demographics.models import Patient
from common.facility_scope import filter_by_patient_facility, filter_by_facility
from .models import AppointmentRequest, PatientRecall
from .workforce_services import staff_at, reason_required
from .workforce_views import staff_choices, datetime_field


def reception(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','reception','clinician','nurse')):raise PermissionDenied


@login_required
def requests(request):
    reception(request.user)
    rows=filter_by_patient_facility(AppointmentRequest.objects.select_related('patient','grant__verified_recipient','appointment'),request.user).order_by('status','preferred_date','pk')
    return render(request,'operations/appointment_requests.html',{'page':Paginator(rows,25).get_page(request.GET.get('page'))})


@login_required
def request_review(request,pk):
    reception(request.user)
    obj=get_object_or_404(filter_by_patient_facility(AppointmentRequest.objects.select_related('patient'),request.user),pk=pk)
    class Form(forms.Form):
        decision=forms.ChoiceField(choices=[('booked','Approve request'),('declined','Decline with explanation')])
        clinician=forms.ModelChoiceField(queryset=staff_choices(request.user).filter(role='clinician',staff_profile__facility_id=obj.patient.facility_id),required=False)
        scheduled_for=datetime_field(required=False)
        duration_minutes=forms.IntegerField(min_value=1,max_value=1440,initial=30,required=False)
        response_note=forms.CharField(max_length=250)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                patient=Patient.objects.select_for_update().get(pk=obj.patient_id)
                if patient.merged_into_id:raise ValidationError('Patient identity changed. Reload.')
                obj=AppointmentRequest.objects.select_for_update().get(pk=pk)
                if obj.status!='requested':return redirect('suite-appointment-requests')
                data=form.cleaned_data
                if data['decision']=='booked' and obj.kind!='new':
                    from apps.accounts.models import User
                    initial=Appointment.objects.get(pk=obj.target_appointment_id,patient=patient)
                    User.objects.select_for_update().get(pk=initial.clinician_id)
                    target=Appointment.objects.select_for_update().get(pk=initial.pk)
                    if target.status not in ('scheduled','confirmed') or target.scheduled_for<=timezone.now() or target.scheduled_for!=obj.target_scheduled_for:raise ValidationError('Booking changed or has started. Decline this stale request and arrange a new one.')
                    if obj.kind=='cancel':target.status='cancelled'
                    else:
                        if not data['scheduled_for'] or data['scheduled_for']<=timezone.now():raise ValidationError('Choose a future replacement time.')
                        target.scheduled_for=data['scheduled_for']
                        if data['duration_minutes']:target.duration_minutes=data['duration_minutes']
                        if data['clinician']:
                            staff_at(data['clinician'],patient.facility_id)
                            if data['clinician'].pk!=target.clinician_id:raise ValidationError('Rescheduling retains the clinician. Use a separately reviewed new booking to change clinician.')
                    target.notes=(target.notes+'\nPatient request #'+str(obj.pk)+': '+data['response_note']).strip()
                    target.save()
                elif data['decision']=='booked':
                    if not data['clinician'] or not data['scheduled_for'] or not data['duration_minutes'] or data['scheduled_for']<=timezone.now():raise ValidationError('Choose a clinician, future appointment time and duration.')
                    staff_at(data['clinician'],patient.facility_id)
                    # Appointment.save applies existing clinician/room/time-off/theatre overlap checks.
                    obj.appointment=Appointment.objects.create(patient=patient,clinician=data['clinician'],scheduled_for=data['scheduled_for'],duration_minutes=data['duration_minutes'],reason_for_visit=obj.reason)
                obj.status=data['decision'];obj.reviewed_by=request.user;obj.reviewed_at=timezone.now();obj.response_note=data['response_note'];obj._history_user=request.user;obj.save()
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-appointment-requests')
    return render(request,'operations/workflow_form.html',{'form':form,'patient':obj.patient,'title':'Review appointment request','help':f'{obj.get_kind_display()}. Preferred date: {obj.preferred_date}. Reason: {obj.reason}. A booking change updates the original appointment only after your approval.'})


@login_required
def recalls(request):
    reception(request.user)
    class Form(forms.ModelForm):
        class Meta:
            model=PatientRecall
            fields=['patient','owner','purpose','due_on','repeat_days']
            widgets={'due_on':forms.DateInput(attrs={'type':'date'})}
    form=Form(request.POST or None)
    form.fields['patient'].queryset=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),request.user)
    form.fields['owner'].queryset=staff_choices(request.user).filter(role__in=['admin','clinician','nurse','reception'])
    if request.method=='POST' and form.is_valid():
        try:
            if not (request.user.is_superuser or request.user.role in ('admin','clinician','nurse')):raise PermissionDenied
            with transaction.atomic():
                patient=Patient.objects.select_for_update().get(pk=form.cleaned_data['patient'].pk)
                if patient.merged_into_id:raise ValidationError('Patient identity changed.')
                staff_at(form.cleaned_data['owner'],patient.facility_id)
                obj=form.save(commit=False);obj.created_by=request.user;obj.save()
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-recalls')
    rows=filter_by_patient_facility(PatientRecall.objects.filter(status='open').select_related('patient','owner'),request.user).order_by('due_on','pk')
    return render(request,'operations/recalls.html',{'form':form,'page':Paginator(rows,25).get_page(request.GET.get('page')),'today':timezone.localdate()})


@login_required
def recall_action(request,pk):
    reception(request.user)
    if request.method!='POST':return HttpResponse('Use POST.',status=405)
    obj=get_object_or_404(filter_by_patient_facility(PatientRecall.objects.all(),request.user),pk=pk)
    if request.user.pk!=obj.owner_id and not (request.user.is_superuser or request.user.role=='admin'):raise PermissionDenied
    try:
        reason=request.POST.get('reason','')[:250];reason_required(reason);decision=request.POST.get('decision')
        if decision not in ('completed','cancelled'):raise ValidationError('Choose completed or cancelled.')
        with transaction.atomic():
            patient=Patient.objects.select_for_update().get(pk=obj.patient_id)
            if patient.merged_into_id:raise ValidationError('Patient identity changed.')
            obj=PatientRecall.objects.select_for_update().get(pk=pk)
            if obj.status=='open':
                if decision=='completed' and obj.repeat_days:
                    staff_at(obj.owner,patient.facility_id)
                    obj.next_recall=PatientRecall.objects.create(patient=patient,owner=obj.owner,purpose=obj.purpose,due_on=timezone.localdate()+timedelta(days=obj.repeat_days),repeat_days=obj.repeat_days,created_by=request.user)
                obj.status=decision;obj.outcome=reason;obj.completed_at=timezone.now();obj._history_user=request.user;obj.save()
                from .models import RecallOutreach, Reminder, WorkTask
                link=RecallOutreach.objects.filter(recall=obj).first()
                if link and link.reminder_id:
                    reminder=Reminder.objects.select_for_update().get(pk=link.reminder_id)
                    if reminder.status in ('pending','failed'):
                        reminder.status='cancelled';reminder.last_error='Recall closed';reminder._history_user=request.user;reminder.save()
                if link and link.escalation_id:
                    task=WorkTask.objects.select_for_update().get(pk=link.escalation_id)
                    if task.status in ('open','in_progress'):
                        task.status='completed' if decision=='completed' else 'cancelled';task.resolution='Recall closed: '+reason;task.resolved_at=timezone.now();task.revision+=1;task._history_user=request.user;task.save()
    except ValidationError as exc:messages.error(request,'; '.join(exc.messages))
    return redirect('suite-recalls')
