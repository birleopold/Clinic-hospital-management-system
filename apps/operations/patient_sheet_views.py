"""Printable patient directions and discharge copies from existing source records."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404,render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from apps.accounts.models import FacilityConfiguration
from apps.demographics.models import Patient
from apps.appointments.models import Appointment, QueueTicket
from common.facility_scope import filter_by_facility
from common.service_policy import enabled
from .models import DiagnosticWorkItem, Admission, PatientRecall


@login_required
@never_cache
def itinerary(request,pk):
    if not (request.user.is_superuser or request.user.role in ('admin','reception','clinician','nurse')):raise PermissionDenied
    patient=get_object_or_404(filter_by_facility(Patient.objects.filter(merged_into__isnull=True),request.user),pk=pk)
    services=[]
    if enabled(request.user,'lab'):services.append('lab')
    if enabled(request.user,'imaging'):services.append('imaging')
    if enabled(request.user,'clinical'):services.append('procedure')
    return render(request,'operations/patient_itinerary.html',{
        'patient':patient,'printed_at':timezone.now(),'facility_brand':FacilityConfiguration.objects.filter(facility_id=patient.facility_id).first(),
        'bookings':Appointment.objects.filter(patient=patient,status__in=['scheduled','confirmed'],scheduled_for__gte=timezone.now()).select_related('room','clinician').order_by('scheduled_for')[:30] if enabled(request.user,'appointments') else [],
        'tickets':QueueTicket.objects.filter(patient=patient,status__in=['waiting','in_service']).select_related('assigned_to').order_by('created_at')[:30] if enabled(request.user,'appointments') else [],
        'diagnostics':DiagnosticWorkItem.objects.filter(order__patient=patient,order__order_type__in=services,completed_at__isnull=True).exclude(order__status='cancelled').select_related('order','operator','room').order_by('scheduled_at','pk')[:30]})


@login_required
@never_cache
def discharge(request,pk):
    if not (request.user.is_superuser or request.user.role in ('admin','clinician','nurse')):raise PermissionDenied
    admission=get_object_or_404(filter_by_facility(Admission.objects.select_related('patient','bed'),request.user,'patient__facility_id'),pk=pk,discharged_at__isnull=False)
    if not enabled(request.user,'inpatient'):raise PermissionDenied
    return render(request,'operations/discharge_sheet.html',{'admission':admission,'patient':admission.patient,'printed_at':timezone.now(),'recalls':PatientRecall.objects.filter(patient=admission.patient,status='open').order_by('due_on')[:30] if enabled(request.user,'engagement') else [],'facility_brand':FacilityConfiguration.objects.filter(facility_id=admission.patient.facility_id).first()})
