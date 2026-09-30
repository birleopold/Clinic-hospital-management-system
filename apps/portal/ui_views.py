import uuid
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Prefetch
from apps.operations.models import PortalGrant, PortalRecipient, AppointmentRequest, DiagnosticWorkItem
from apps.orders.models import OrderResult
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.orders.models import Order
from apps.pharmacy.models import Prescription
from apps.billing.models import Invoice
from apps.appointments.models import Appointment
from common.facility_scope import filter_by_facility


# Config: default max age 72 hours
MAX_AGE = getattr(settings, 'PATIENT_PORTAL_TOKEN_MAX_AGE', 72 * 3600)
SALT = 'patient-portal'


@never_cache
def portal_view(request, token: str):
    from .access import authorize, diagnostic_types
    grant,recipient,scopes=authorize(token)
    patient=grant.patient
    class RequestForm(forms.Form):
        preferred_date=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
        reason=forms.CharField(max_length=250,label='Reason for appointment')
        request_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput())
    appointment_form=RequestForm(request.POST or None) if 'appointments' in scopes else None
    if request.method=='POST':
        if 'appointments' not in scopes:return HttpResponseForbidden('This link is read-only.')
        if appointment_form.is_valid():
            data=appointment_form.cleaned_data
            if data['preferred_date']<timezone.localdate() or data['preferred_date']>timezone.localdate()+timedelta(days=365):appointment_form.add_error('preferred_date','Choose a date from today to one year ahead.')
            else:
                with transaction.atomic():
                    locked=Patient.objects.select_for_update().get(pk=patient.pk)
                    authorize(token,'appointments',lock=True)
                    if locked.merged_into_id:return HttpResponseForbidden('This link is no longer active.')
                    previous=AppointmentRequest.objects.filter(request_key=data['request_key']).first()
                    if previous:
                        if previous.grant_id!=grant.pk or previous.preferred_date!=data['preferred_date'] or previous.reason!=data['reason']:appointment_form.add_error(None,'Request reference conflict. Reload the page.')
                    elif AppointmentRequest.objects.filter(patient=patient,status='requested').count()>=5:appointment_form.add_error(None,'You already have five pending requests. Please contact reception.')
                    else:AppointmentRequest.objects.create(grant=grant,patient=patient,**data)
                if not appointment_form.errors:
                    from django.shortcuts import redirect
                    return redirect('portal-view',token=token)

    encounters = Encounter.objects.filter(patient=patient).select_related('clinician').order_by('-id')[:50] if 'visits' in scopes else []
    lab_orders = Order.objects.filter(patient=patient, order_type__in=diagnostic_types(grant)).prefetch_related(Prefetch('results', queryset=OrderResult.objects.filter(approved_at__isnull=False))).order_by('-id')[:50] if 'results' in scopes else []
    prescriptions = Prescription.objects.filter(patient=patient).prefetch_related('items').order_by('-id')[:50] if 'medicines' in scopes else []
    invoices = Invoice.objects.filter(patient=patient).order_by('-id')[:50] if 'billing' in scopes else []

    context = {
        'scopes':scopes,
        'appointments':Appointment.objects.filter(patient=patient,status__in=['scheduled','confirmed'],scheduled_for__gt=timezone.now()).select_related('clinician').order_by('scheduled_for')[:30] if 'appointments' in scopes else [],
        'preparations':DiagnosticWorkItem.objects.filter(order__patient=patient,order__order_type__in=diagnostic_types(grant),completed_at__isnull=True).exclude(order__status='cancelled').exclude(instructions_snapshot={}).select_related('order','room').order_by('scheduled_at','pk')[:30] if 'instructions' in scopes else [],
        'feedback':grant.feedback.order_by('-pk')[:20] if 'feedback' in scopes else [],
        'appointment_form':appointment_form,
        'appointment_requests':AppointmentRequest.objects.filter(grant=grant).select_related('appointment').order_by('-pk')[:20],
        'token': token,
        'patient': patient,
        'encounters': encounters,
        'lab_orders': lab_orders,
        'prescriptions': prescriptions,
        'invoices': invoices,
    }
    response = render(request, 'portal/view.html', context)
    response['Referrer-Policy'] = 'same-origin'
    return response


@login_required
@never_cache
def token_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','reception','clinician')):
        return HttpResponseForbidden('Not allowed')

    try:
        patient_id = int(request.GET.get('patient_id') or '0')
    except Exception:
        patient_id = 0
    patient = get_object_or_404(filter_by_facility(Patient.objects.all(), user), pk=patient_id) if patient_id else None

    from .access import SCOPES
    class RecipientForm(forms.Form):
        scopes=forms.MultipleChoiceField(choices=SCOPES,initial=['visits','results','medicines','billing'],widget=forms.CheckboxSelectMultiple,required=True,label='Information and actions authorized for this recipient')
        allow_appointment_requests=forms.BooleanField(required=False,label='Allow appointment requests')
        recipient_name=forms.CharField(max_length=160,required=False)
        relationship=forms.ChoiceField(choices=[('patient','Patient'),('guardian','Authorized guardian')],required=False)
        verification_reference=forms.CharField(max_length=250,required=False,label='Identity verification reference (avoid copying identity-document numbers)')
        authority_reference=forms.CharField(max_length=250,required=False,label='Guardian authority / consent reference')
        verified=forms.BooleanField(required=False,label='I verified the recipient identity and authority to receive this patient link')
        def clean(self):
            data=super().clean()
            if data.get('allow_appointment_requests') or data.get('scopes'):
                if not all(data.get(k) for k in ('recipient_name','relationship','verification_reference','verified')):raise forms.ValidationError('Verify the recipient and complete identity evidence before enabling requests.')
                if data.get('allow_appointment_requests') and 'appointments' not in data.get('scopes',[]):raise forms.ValidationError('Select appointment scope before enabling appointment requests.')
                if data.get('relationship')=='guardian' and not data.get('authority_reference'):raise forms.ValidationError('Record the guardian authority/consent reference.')
            return data
    form=RecipientForm(request.POST if request.method=='POST' else None)
    link = None
    if patient and request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            patient=Patient.objects.select_for_update().get(pk=patient.pk)
            if patient.merged_into_id:return HttpResponseForbidden('Select the canonical patient.')
            grant = PortalGrant.objects.create(patient=patient, created_by=user, expires_at=timezone.now()+timedelta(seconds=MAX_AGE))
            if form.cleaned_data['allow_appointment_requests'] or form.cleaned_data['scopes']:
                data={k:form.cleaned_data[k] for k in ('recipient_name','relationship','verification_reference','authority_reference','allow_appointment_requests','scopes')}
                PortalRecipient.objects.create(grant=grant,created_by=user,**data)
            token = signing.dumps({'p': patient.id, 'g': str(grant.key)}, salt=SALT)
            link = request.build_absolute_uri(reverse('portal-view', args=[token]))

    context = {
        'patient': patient,
        'link': link,
        'form':form,
        'max_age_hours': int(MAX_AGE // 3600),
        'grants':PortalGrant.objects.filter(patient=patient).select_related('verified_recipient').order_by('-pk')[:25] if patient else [],
    }
    return render(request, 'portal/token_create.html', context)


@never_cache
def portal_download(request, token, pk):
    from django.http import FileResponse, Http404
    from .access import authorize, diagnostic_types
    grant,recipient,scopes=authorize(token,'results')
    result = get_object_or_404(OrderResult, pk=pk, order__patient_id=grant.patient_id, order__order_type__in=diagnostic_types(grant), approved_at__isnull=False)
    if not result.attachment:
        raise Http404
    response = FileResponse(result.attachment.open('rb'), as_attachment=True, filename=result.attachment.name.rsplit('/',1)[-1])
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
