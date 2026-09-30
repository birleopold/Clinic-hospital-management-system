import uuid
from datetime import timedelta
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import render,redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.utils import timezone
from apps.accounts.models import User
from apps.demographics.models import Patient
from apps.appointments.models import Appointment
from apps.operations.models import AppointmentRequest, ManagementCase, PortalGrant
from .access import authorize


@never_cache
def change(request,token,pk):
    grant,recipient,scopes=authorize(token,'appointments')
    from django.shortcuts import get_object_or_404
    appointment=get_object_or_404(Appointment,pk=pk,patient_id=grant.patient_id,status__in=['scheduled','confirmed'],scheduled_for__gt=timezone.now())
    class Form(forms.Form):
        kind=forms.ChoiceField(choices=[('reschedule','Request a different date'),('cancel','Request cancellation')])
        preferred_date=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
        reason=forms.CharField(max_length=250)
        request_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput())
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        if data['kind']=='reschedule' and (not data['preferred_date'] or not timezone.localdate()<=data['preferred_date']<=timezone.localdate()+timedelta(days=365)):
            form.add_error('preferred_date','Choose a date from today to one year ahead.')
        else:
            try:
                with transaction.atomic():
                    patient=Patient.objects.select_for_update().get(pk=grant.patient_id)
                    grant,recipient,scopes=authorize(token,'appointments',lock=True)
                    current=Appointment.objects.get(pk=pk,patient=patient)
                    if current.status not in ('scheduled','confirmed') or current.scheduled_for<=timezone.now():raise ValidationError('This booking is no longer available for changes.')
                    day=data['preferred_date'] if data['kind']=='reschedule' else timezone.localtime(current.scheduled_for).date()
                    previous=AppointmentRequest.objects.filter(request_key=data['request_key']).first()
                    if previous:
                        if previous.grant_id!=grant.pk or previous.target_appointment_id!=pk or previous.kind!=data['kind'] or previous.reason!=data['reason'] or previous.preferred_date!=day:raise ValidationError('Request reference conflict. Reload.')
                    elif AppointmentRequest.objects.filter(target_appointment_id=pk,status='requested').exists():raise ValidationError('Reception already has a pending change for this booking.')
                    else:AppointmentRequest.objects.create(grant=grant,patient=patient,kind=data['kind'],target_appointment=current,target_scheduled_for=current.scheduled_for,preferred_date=day,reason=data['reason'],request_key=data['request_key'])
            except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
            else:return redirect('portal-view',token=token)
    response=render(request,'portal/action.html',{'form':form,'token':token,'title':'Request a booking change','help':f'Current booking: {appointment.scheduled_for}. Reception reviews all changes; your current slot remains until approved.'})
    response['Referrer-Policy']='same-origin'
    return response


@never_cache
def feedback(request,token):
    grant,recipient,scopes=authorize(token,'feedback')
    class Form(forms.Form):
        title=forms.CharField(max_length=160)
        details=forms.CharField(max_length=2000,widget=forms.Textarea,help_text='Avoid identity-document numbers. For urgent clinical problems contact the facility directly.')
        request_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput())
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                patient=Patient.objects.select_for_update().get(pk=grant.patient_id)
                grant,recipient,scopes=authorize(token,'feedback',lock=True)
                data=form.cleaned_data
                previous=ManagementCase.objects.filter(submission_key=data['request_key']).first()
                if previous:
                    if previous.source_grant_id!=grant.pk or previous.title!=data['title'] or previous.details!=data['details']:raise ValidationError('Submission reference conflict. Reload.')
                else:
                    if ManagementCase.objects.filter(source_grant=grant,status__in=['open','review']).count()>=5:raise ValidationError('Please contact reception about existing feedback before submitting more.')
                    owner=User.objects.filter(staff_profile__facility_id=patient.facility_id,is_active=True,role__in=['admin','manager']).order_by('pk').first()
                    if not owner:raise ValidationError('Please contact reception; no feedback manager is currently assigned.')
                    ManagementCase.objects.create(facility_id=patient.facility_id,kind='complaint',severity='moderate',title=data['title'],details=data['details'],owner=owner,due_at=timezone.now()+timedelta(days=2),source_grant=grant,submission_key=data['request_key'])
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('portal-view',token=token)
    response=render(request,'portal/action.html',{'form':form,'token':token,'title':'Send feedback','help':'Your feedback enters the restricted facility manager register. The portal shows receipt and status, without revealing internal investigation notes.'})
    response['Referrer-Policy']='same-origin'
    return response


@never_cache
@require_POST
def revoke(request,token):
    grant,recipient,scopes=authorize(token)
    with transaction.atomic():
        Patient.objects.select_for_update().get(pk=grant.patient_id)
        grant,recipient,scopes=authorize(token,lock=True)
        grant.revoked_at=timezone.now();grant.save(update_fields=['revoked_at'])
    return render(request,'portal/revoked.html')


@never_cache
@require_POST
def acknowledge_instructions(request,token,pk):
    from .access import diagnostic_types
    grant,recipient,scopes=authorize(token,'instructions')
    from apps.operations.models import DiagnosticWorkItem
    from django.shortcuts import get_object_or_404
    with transaction.atomic():
        Patient.objects.select_for_update().get(pk=grant.patient_id)
        grant,recipient,scopes=authorize(token,'instructions',lock=True)
        item=get_object_or_404(DiagnosticWorkItem.objects.select_for_update(),pk=pk,order__patient_id=grant.patient_id,order__order_type__in=diagnostic_types(grant),completed_at__isnull=True)
        if item.order.status=='cancelled' or not item.instructions_snapshot:return HttpResponseForbidden('No active approved instructions.')
        if str(item.revision)!=request.POST.get('revision'):return HttpResponseForbidden('Instructions changed. Reload before acknowledging.')
        if not item.instructions_acknowledged_at:
            item.instructions_acknowledged_at=timezone.now();item.instructions_acknowledged_grant=grant;item.save(update_fields=['instructions_acknowledged_at','instructions_acknowledged_grant'])
    return redirect('portal-view',token=token)
