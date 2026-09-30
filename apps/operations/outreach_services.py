import re
from datetime import timedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone
from apps.demographics.models import Patient
from common.facility_scope import filter_by_facility
from .models import ContactPreference, Reminder, ReminderAttempt, PatientRecall, RecallOutreach, WorkTask


def actor_allowed(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','clinician','nurse','reception')):raise PermissionDenied


@transaction.atomic
def set_preference(patient_id,actor,allowed,phone,evidence):
    actor_allowed(actor)
    patient=filter_by_facility(Patient.objects.select_for_update(),actor).filter(pk=patient_id).first()
    if not patient:raise PermissionDenied
    if patient.merged_into_id:raise ValidationError('Patient identity changed.')
    if not evidence.strip():raise ValidationError('Record consent or opt-out evidence.')
    if allowed and (not re.fullmatch(r'\+[1-9][0-9]{7,14}',phone) or phone!=patient.phone):raise ValidationError('Verify the patient’s current phone in international +country-code format first.')
    obj,_=ContactPreference.objects.get_or_create(patient=patient,defaults={'created_by':actor,'evidence':evidence})
    obj.sms_allowed=allowed;obj.verified_phone=phone if allowed else '';obj.evidence=evidence;obj._history_user=actor;obj.save()
    if not allowed:
        for job in Reminder.objects.filter(patient=patient,status__in=['pending','failed']):
            job.status='cancelled';job.last_error='Patient opted out';job._history_user=actor;job.save()
    return obj


def consent_valid(job):
    pref=ContactPreference.objects.filter(patient_id=job.patient_id,sms_allowed=True).first()
    return bool(job.consent_confirmed and pref and pref.verified_phone and pref.verified_phone==job.patient.phone and not job.patient.merged_into_id and not RecallOutreach.objects.filter(reminder=job).exclude(recall__status='open').exists())


@transaction.atomic
def retry(pk,actor):
    actor_allowed(actor)
    candidate=Reminder.objects.get(pk=pk)
    patient=filter_by_facility(Patient.objects.select_for_update(),actor).filter(pk=candidate.patient_id).first()
    if not patient or patient.merged_into_id:raise PermissionDenied
    job=Reminder.objects.select_for_update().get(pk=pk)
    if job.patient_id!=patient.pk:raise ValidationError('Patient identity changed; reload.')
    if job.status!='failed' or job.attempts>=3 or job.delivery_attempts.filter(outcome='review').exists():raise ValidationError('Only confirmed failed deliveries under three attempts can be retried. Reconcile uncertain outcomes with the provider.')
    if not consent_valid(job):raise ValidationError('Current verified consent is required.')
    job.status='pending';job._history_user=actor;job.save();return job


@transaction.atomic
def queue_recall(pk,horizon_days=3):
    initial=PatientRecall.objects.get(pk=pk)
    patient=Patient.objects.select_for_update().get(pk=initial.patient_id)
    recall=PatientRecall.objects.select_for_update().get(pk=pk)
    if recall.patient_id!=patient.pk or patient.merged_into_id or recall.status!='open' or recall.due_on>timezone.localdate()+timedelta(days=horizon_days):return None
    link,_=RecallOutreach.objects.get_or_create(recall=recall)
    pref=ContactPreference.objects.filter(patient=patient,sms_allowed=True,verified_phone=patient.phone).first()
    if pref and pref.verified_phone and not link.reminder_id:
        link.reminder=Reminder.objects.create(patient=patient,created_by=recall.created_by,scheduled_for=timezone.now(),consent_confirmed=True,body='Please contact your clinic about a follow-up. No appointment is confirmed by this message.')
    if recall.due_on<timezone.localdate() and not link.escalation_id and recall.owner.is_active and getattr(getattr(recall.owner,'staff_profile',None),'facility_id',None)==patient.facility_id:
        link.escalation=WorkTask.objects.create(patient=patient,facility=patient.facility,created_by=recall.created_by,owner=recall.owner,audience=recall.owner.role,title='Overdue patient follow-up',instruction=f'Review recall #{recall.pk}; confirm contact preferences before outreach.',source_kind='recall',source_pk=recall.pk,due_at=timezone.now())
    link.save();return link
