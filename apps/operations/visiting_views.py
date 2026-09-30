from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from apps.accounts.models import User
from apps.demographics.models import Patient
from common.facility_scope import filter_by_patient_facility, filter_by_facility
from .models import VisitingSpecialist, VisitingEngagement, VisitingCaseNote, TheatreCase
from .workforce_services import facility_lock, reason_required
from .workforce_views import datetime_field, staff_choices


def active_grants(user):
    now=timezone.now()
    return VisitingEngagement.objects.filter(specialist__user=user,case__surgeon=user,starts_at__lte=now,ends_at__gt=now,revoked_at__isnull=True,specialist__credential_expires__gte=timezone.localdate(),case__patient__merged_into__isnull=True,case__patient__facility_id=F('specialist__user__staff_profile__facility_id')).exclude(case__status='cancelled')


def administrators(user):
    if not user.is_active or not (user.is_superuser or user.role=='admin'):raise PermissionDenied


@login_required
def portal(request):
    if not VisitingSpecialist.objects.filter(user=request.user).exists():raise PermissionDenied
    return render(request,'operations/visiting_portal.html',{'grants':active_grants(request.user).select_related('case__patient','case__room').order_by('case__starts_at')[:50]})


@login_required
def case(request,pk):
    grant=get_object_or_404(active_grants(request.user).select_related('case__patient','case__room'),pk=pk)
    class Form(forms.Form):
        body=forms.CharField(widget=forms.Textarea,help_text='Signed case note. It cannot be overwritten; add a referenced amendment for corrections.')
        amends=forms.ModelChoiceField(queryset=grant.notes.all(),required=False)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                patient=Patient.objects.select_for_update().get(pk=grant.case.patient_id)
                if patient.merged_into_id:raise ValidationError('Patient identity changed. Contact the facility team.')
                locked=get_object_or_404(active_grants(request.user).select_for_update(of=('self',)),pk=pk)
                note=VisitingCaseNote.objects.create(engagement=locked,body=form.cleaned_data['body'],amends=form.cleaned_data['amends'],created_by=request.user)
                messages.success(request,'Signed case note recorded.')
                return redirect('visiting-case',pk=pk)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
    return render(request,'operations/visiting_case.html',{'grant':grant,'case':grant.case,'notes':grant.notes.select_related('created_by').order_by('created_at'),'form':form})


@login_required
def manage(request):
    administrators(request.user)
    specialists=filter_by_facility(VisitingSpecialist.objects.select_related('user'),request.user,field='user__staff_profile__facility_id')
    grants=filter_by_patient_facility(VisitingEngagement.objects.select_related('specialist__user','case__patient'),request.user,prefix='case__patient__').order_by('-pk')[:50]
    return render(request,'operations/visiting_manage.html',{'specialists':specialists,'grants':grants})


@login_required
def create(request,kind):
    administrators(request.user)
    if kind=='specialist':
        class Form(forms.ModelForm):
            class Meta:
                model=VisitingSpecialist
                fields=['user','specialty','credential_reference','credential_expires','verification_note']
                widgets={'credential_expires':forms.DateInput(attrs={'type':'date'})}
        form=Form(request.POST or None);form.fields['user'].queryset=staff_choices(request.user).filter(role='clinician',is_superuser=False,is_staff=False)
    elif kind=='engagement':
        class Form(forms.ModelForm):
            starts_at=datetime_field()
            ends_at=datetime_field()
            class Meta:
                model=VisitingEngagement
                fields=['specialist','case','starts_at','ends_at','purpose']
        form=Form(request.POST or None)
        form.fields['specialist'].queryset=filter_by_facility(VisitingSpecialist.objects.all(),request.user,field='user__staff_profile__facility_id')
        form.fields['case'].queryset=filter_by_patient_facility(TheatreCase.objects.exclude(status='cancelled'),request.user)
    else:raise PermissionDenied
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj=form.save(commit=False)
                if kind=='specialist':
                    user=User.objects.select_for_update().get(pk=obj.user_id)
                    if user.role!='clinician' or user.is_superuser or user.is_staff:raise ValidationError('Use a dedicated non-admin clinician account for the visiting specialist.')
                    if obj.credential_expires<timezone.localdate():raise ValidationError('Record a currently valid reviewed credential.')
                else:
                    patient=Patient.objects.select_for_update().get(pk=obj.case.patient_id)
                    facility_lock(request.user,patient.facility_id)
                    obj.case=TheatreCase.objects.select_for_update().get(pk=obj.case_id)
                    if patient.merged_into_id or obj.case.patient_id!=patient.pk:raise ValidationError('Patient identity changed. Reload.')
                    if obj.case.surgeon_id!=obj.specialist.user_id or obj.specialist.user.staff_profile.facility_id!=patient.facility_id:raise ValidationError('The specialist must be this case’s assigned surgeon in the same facility.')
                    if obj.ends_at<=timezone.now() or obj.starts_at>obj.case.starts_at or obj.ends_at<obj.case.ends_at or obj.ends_at-obj.starts_at>timedelta(days=30):raise ValidationError('Use an access window covering the case, up to 30 days.')
                    if obj.specialist.credential_expires<timezone.localtime(obj.ends_at).date():raise ValidationError('Credential expires before the end of access.')
                obj.created_by=request.user;obj.save()
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-visiting-manage')
    help_text='Use a dedicated clinician account. Registering it here restricts its entire web/API access to the visiting-case portal, including previously issued API tokens. Share account credentials only after restriction and case authorization are configured.' if kind=='specialist' else 'Authorize only the assigned case and agreed dates. No blanket access to the facility patient list is granted.'
    return render(request,'operations/workflow_form.html',{'form':form,'title':'Register visiting specialist' if kind=='specialist' else 'Authorize visiting case','help':help_text})


@login_required
def revoke(request,pk):
    administrators(request.user)
    if request.method!='POST':return HttpResponse('Use POST.',status=405)
    grant=get_object_or_404(filter_by_patient_facility(VisitingEngagement.objects.all(),request.user,prefix='case__patient__'),pk=pk)
    reason=request.POST.get('reason','').strip()[:250]
    if not reason:messages.error(request,'A revocation reason is required.')
    else:
        with transaction.atomic():
            Patient.objects.select_for_update().get(pk=grant.case.patient_id)
            grant=VisitingEngagement.objects.select_for_update().get(pk=pk)
            if not grant.revoked_at:grant.revoked_at=timezone.now();grant.revoke_reason=reason;grant._history_user=request.user;grant.save()
        messages.success(request,'Case access revoked. Signed notes remain in history.')
    return redirect('suite-visiting-manage')
