import uuid
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Prefetch
from apps.operations.models import PortalGrant, PortalRecipient, AppointmentRequest
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
from common.facility_scope import filter_by_facility


# Config: default max age 72 hours
MAX_AGE = getattr(settings, 'PATIENT_PORTAL_TOKEN_MAX_AGE', 72 * 3600)
SALT = 'patient-portal'


@never_cache
def portal_view(request, token: str):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        patient_id = int(data.get('p'))
    except Exception:
        return HttpResponseForbidden('Invalid or expired link')

    grant = PortalGrant.objects.filter(key=data.get('g'), patient_id=patient_id, revoked_at__isnull=True, expires_at__gt=timezone.now()).first() if data.get('g') else None
    if not grant:
        return HttpResponseForbidden('Invalid or revoked link')
    patient = get_object_or_404(Patient, pk=patient_id,merged_into__isnull=True)
    recipient=PortalRecipient.objects.filter(grant=grant,allow_appointment_requests=True).first()
    class RequestForm(forms.Form):
        preferred_date=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
        reason=forms.CharField(max_length=250,label='Reason for appointment')
        request_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput())
    appointment_form=RequestForm(request.POST or None) if recipient else None
    if request.method=='POST':
        if not recipient:return HttpResponseForbidden('This link is read-only.')
        if appointment_form.is_valid():
            data=appointment_form.cleaned_data
            if data['preferred_date']<timezone.localdate() or data['preferred_date']>timezone.localdate()+timedelta(days=365):appointment_form.add_error('preferred_date','Choose a date from today to one year ahead.')
            else:
                with transaction.atomic():
                    locked=Patient.objects.select_for_update().get(pk=patient.pk)
                    active=PortalGrant.objects.select_for_update().filter(pk=grant.pk,revoked_at__isnull=True,expires_at__gt=timezone.now()).exists()
                    if locked.merged_into_id or not active:return HttpResponseForbidden('This link is no longer active.')
                    previous=AppointmentRequest.objects.filter(request_key=data['request_key']).first()
                    if previous:
                        if previous.grant_id!=grant.pk or previous.preferred_date!=data['preferred_date'] or previous.reason!=data['reason']:appointment_form.add_error(None,'Request reference conflict. Reload the page.')
                    elif AppointmentRequest.objects.filter(patient=patient,status='requested').count()>=5:appointment_form.add_error(None,'You already have five pending requests. Please contact reception.')
                    else:AppointmentRequest.objects.create(grant=grant,patient=patient,**data)
                if not appointment_form.errors:
                    from django.shortcuts import redirect
                    return redirect('portal-view',token=token)

    encounters = Encounter.objects.filter(patient=patient).select_related('clinician').order_by('-id')[:50]
    lab_orders = Order.objects.filter(patient=patient, order_type__in=[Order.LAB,Order.IMAGING,Order.PROCEDURE]).prefetch_related(Prefetch('results', queryset=OrderResult.objects.filter(approved_at__isnull=False))).order_by('-id')[:50]
    prescriptions = Prescription.objects.filter(patient=patient).prefetch_related('items').order_by('-id')[:50]
    invoices = Invoice.objects.filter(patient=patient).order_by('-id')[:50]

    context = {
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
    response['Referrer-Policy'] = 'no-referrer'
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

    class RecipientForm(forms.Form):
        allow_appointment_requests=forms.BooleanField(required=False,label='Allow appointment requests')
        recipient_name=forms.CharField(max_length=160,required=False)
        relationship=forms.ChoiceField(choices=[('patient','Patient'),('guardian','Authorized guardian')],required=False)
        verification_reference=forms.CharField(max_length=250,required=False,label='Identity verification reference (avoid copying identity-document numbers)')
        authority_reference=forms.CharField(max_length=250,required=False,label='Guardian authority / consent reference')
        verified=forms.BooleanField(required=False,label='I verified the recipient identity and authority to receive this patient link')
        def clean(self):
            data=super().clean()
            if data.get('allow_appointment_requests'):
                if not all(data.get(k) for k in ('recipient_name','relationship','verification_reference','verified')):raise forms.ValidationError('Verify the recipient and complete identity evidence before enabling requests.')
                if data.get('relationship')=='guardian' and not data.get('authority_reference'):raise forms.ValidationError('Record the guardian authority/consent reference.')
            return data
    form=RecipientForm(request.POST if request.method=='POST' else None)
    link = None
    if patient and request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            patient=Patient.objects.select_for_update().get(pk=patient.pk)
            if patient.merged_into_id:return HttpResponseForbidden('Select the canonical patient.')
            grant = PortalGrant.objects.create(patient=patient, created_by=user, expires_at=timezone.now()+timedelta(seconds=MAX_AGE))
            if form.cleaned_data['allow_appointment_requests']:
                data={k:form.cleaned_data[k] for k in ('recipient_name','relationship','verification_reference','authority_reference','allow_appointment_requests')}
                PortalRecipient.objects.create(grant=grant,created_by=user,**data)
            token = signing.dumps({'p': patient.id, 'g': str(grant.key)}, salt=SALT)
            link = request.build_absolute_uri(reverse('portal-view', args=[token]))

    context = {
        'patient': patient,
        'link': link,
        'form':form,
        'max_age_hours': int(MAX_AGE // 3600),
    }
    return render(request, 'portal/token_create.html', context)


@never_cache
def portal_download(request, token, pk):
    from django.http import FileResponse, Http404
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        grant = PortalGrant.objects.get(key=data.get('g'), patient_id=data.get('p'), revoked_at__isnull=True, expires_at__gt=timezone.now())
    except Exception:
        return HttpResponseForbidden('Invalid or expired link')
    result = get_object_or_404(OrderResult, pk=pk, order__patient_id=grant.patient_id, approved_at__isnull=False)
    if not result.attachment:
        raise Http404
    response = FileResponse(result.attachment.open('rb'), as_attachment=True, filename=result.attachment.name.rsplit('/',1)[-1])
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
