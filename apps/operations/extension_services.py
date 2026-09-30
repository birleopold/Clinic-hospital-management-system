"""Explicitly reviewed, facility-scoped workflows. No inferred clinical rules."""
import re
from urllib.parse import urlsplit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from apps.demographics.models import Patient
from common.facility_scope import filter_by_facility
from .diagnostic_services import locked_order
from .workforce_services import staff_at, reason_required
from .models import (Specimen, SpecimenCustody, SpecimenAliquot, ReagentLot,
    LaboratoryQC, LabRunEvidence, FacilityAsset, DiagnosticWorksheet,
    ProgrammeDefinition, ProgrammeEnrollment, ProgrammeReview, ImagingStudy)


def role(actor, roles):
    if not actor.is_active or not (actor.is_superuser or actor.role in roles):
        raise PermissionDenied


def scoped_lock(model, pk, actor):
    obj = filter_by_facility(model.objects.select_for_update(), actor).filter(pk=pk).first()
    if not obj:
        raise PermissionDenied
    return obj


def save_valid(obj, actor):
    obj.created_by = actor
    obj.full_clean(exclude=['created_at'])
    obj._history_user = actor
    obj.save()
    return obj


@transaction.atomic
def custody(specimen_id, actor, **data):
    role(actor, ('admin', 'lab'))
    initial = Specimen.objects.get(pk=specimen_id)
    order = locked_order(initial.order_id, actor)
    specimen = Specimen.objects.select_for_update().get(pk=specimen_id)
    if order.order_type != 'lab' or order.status == 'cancelled':
        raise ValidationError('Use a non-cancelled laboratory order.')
    existing = specimen.custody_events.filter(reference=data['reference']).first()
    if existing:
        if existing.created_by_id != actor.pk or any(getattr(existing, key) != value for key, value in data.items()):
            raise ValidationError('Reference already used for different custody details.')
        return existing
    previous = specimen.custody_events.order_by('-occurred_at', '-pk').first()
    if data['occurred_at'] > timezone.now() or data['occurred_at'] < specimen.created_at:
        raise ValidationError('Custody time must be between specimen registration and now.')
    if previous and (previous.event == 'disposed' or data['occurred_at'] < previous.occurred_at or data['from_location'] != previous.to_location):
        raise ValidationError('Continue from the latest custody location and time; disposed specimens cannot move.')
    return save_valid(SpecimenCustody(specimen=specimen, **data), actor)


@transaction.atomic
def aliquot(parent_id, actor, quantity, unit, reason):
    role(actor, ('admin', 'lab'))
    initial = Specimen.objects.get(pk=parent_id)
    order = locked_order(initial.order_id, actor)
    parent = Specimen.objects.select_for_update().get(pk=parent_id)
    if order.order_type != 'lab' or order.status != 'ordered' or parent.status != 'received' or parent.custody_events.filter(event='disposed').exists():
        raise ValidationError('Use a received, undisposed specimen on an open laboratory order.')
    child = Specimen.objects.create(order=order, specimen_type=parent.specimen_type, status='collected', created_by=actor)
    return save_valid(SpecimenAliquot(parent=parent, child=child, quantity=quantity, unit=unit, reason=reason), actor)


@transaction.atomic
def reagent_create(actor, **data):
    role(actor, ('admin', 'lab'))
    from .workforce_services import facility_lock
    facility_lock(actor, data['facility'].pk)
    if data.get('use_by') and data['use_by'] > data['expires_on']:
        raise ValidationError('Use-by cannot exceed expiry.')
    if data.get('opened_on') and (data['opened_on'] > timezone.localdate() or data['opened_on'] > (data.get('use_by') or data['expires_on'])):
        raise ValidationError('Opening date must be no later than today and use-by.')
    return save_valid(ReagentLot(**data), actor)


@transaction.atomic
def reagent_review(pk, actor, release, reason):
    role(actor, ('admin', 'lab'))
    obj = scoped_lock(ReagentLot, pk, actor)
    reason_required(reason)
    if release:
        if obj.created_by_id == actor.pk:
            raise ValidationError('Another laboratory reviewer must release this lot.')
        if min(obj.expires_on, obj.use_by or obj.expires_on) < timezone.localdate():
            raise ValidationError('Expired reagent cannot be released.')
        if LaboratoryQC.objects.filter(reagent=obj, outcome='fail').exists():
            raise ValidationError('Failed QC requires a separately documented replacement lot or validated remediation process; release is blocked.')
    obj.quarantined = not release
    obj.reviewed_by, obj.reviewed_at, obj.review_reason = actor, timezone.now(), reason
    obj._history_user = actor
    obj.save()
    return obj


@transaction.atomic
def qc_create(actor, **data):
    role(actor, ('admin', 'lab'))
    reagent = scoped_lock(ReagentLot, data['reagent'].pk, actor)
    asset = scoped_lock(FacilityAsset, data['asset'].pk, actor)
    if reagent.facility_id != asset.facility_id or data['facility'].pk != reagent.facility_id:
        raise ValidationError('Equipment and reagent must belong to this facility.')
    if data['valid_until'] <= timezone.now():
        raise ValidationError('Record a future review expiry under the approved procedure.')
    obj = save_valid(LaboratoryQC(**data), actor)
    if obj.outcome == 'fail':
        reagent.quarantined = True
        reagent.review_reason = f'Quarantined after failed QC #{obj.pk}'
        reagent._history_user = actor
        reagent.save()
    return obj


@transaction.atomic
def qc_review(pk, actor, reason):
    role(actor, ('admin', 'lab'))
    obj = scoped_lock(LaboratoryQC, pk, actor)
    reason_required(reason)
    if obj.created_by_id == actor.pk:
        raise ValidationError('Another qualified reviewer must review QC.')
    if not obj.reviewed_at:
        obj.reviewed_by, obj.reviewed_at, obj.review_reason = actor, timezone.now(), reason
        obj._history_user = actor
        obj.save()
    return obj


def validate_run(evidence):
    qc = LaboratoryQC.objects.select_for_update().get(pk=evidence.qc_id)
    reagent = ReagentLot.objects.select_for_update().get(pk=qc.reagent_id)
    asset = FacilityAsset.objects.select_for_update().get(pk=qc.asset_id)
    day = timezone.localdate(evidence.run_at)
    if qc.outcome != 'pass' or not qc.reviewed_at or not qc.reviewed_at <= evidence.run_at <= qc.valid_until:
        raise ValidationError('Run must fall inside the independently reviewed passing QC window.')
    if evidence.run_at > timezone.now() or reagent.quarantined or not reagent.reviewed_at or reagent.reviewed_at > evidence.run_at or day > min(reagent.expires_on, reagent.use_by or reagent.expires_on) or (reagent.opened_on and day < reagent.opened_on):
        raise ValidationError('Reagent must be released, unquarantined and valid for the recorded run.')
    if asset.status != 'operational' or (asset.maintenance_due and asset.maintenance_due < day) or (asset.calibration_due and asset.calibration_due < day):
        raise ValidationError('Equipment must be operational with no overdue recorded maintenance/calibration.')


@transaction.atomic
def attach_run(worksheet_id, actor, qc, run_at, reference):
    role(actor, ('admin', 'lab'))
    candidate = DiagnosticWorksheet.objects.select_related('result').get(pk=worksheet_id)
    order = locked_order(candidate.result.order_id, actor)
    sheet = DiagnosticWorksheet.objects.select_for_update().get(pk=worksheet_id)
    if order.order_type != 'lab' or sheet.result.approved_at or sheet.withdrawn_at or order.status != 'ordered':
        raise ValidationError('Attach run evidence before releasing an active laboratory worksheet.')
    if qc.facility_id != order.patient.facility_id:
        raise ValidationError('QC must belong to this facility.')
    evidence = LabRunEvidence(worksheet=sheet, qc=qc, run_at=run_at, reference=reference)
    validate_run(evidence)
    return save_valid(evidence, actor)


@transaction.atomic
def programme_create(actor, **data):
    role(actor, ('admin', 'clinician'))
    from .workforce_services import facility_lock
    facility_lock(actor, data['facility'].pk)
    staff_at(data['clinical_owner'], data['facility'].pk)
    if data['version'] < 1:
        raise ValidationError('Programme versions start at 1.')
    if data['clinical_owner'].role != 'clinician':
        raise ValidationError('Assign an active clinical owner.')
    return save_valid(ProgrammeDefinition(**data), actor)


@transaction.atomic
def programme_review(pk, actor, decision, reason):
    role(actor, ('admin', 'clinician'))
    obj = scoped_lock(ProgrammeDefinition, pk, actor)
    reason_required(reason)
    if obj.created_by_id == actor.pk:
        raise ValidationError('Another qualified reviewer must approve programme changes.')
    if decision not in ('published', 'retired') or (decision == 'published' and obj.status != 'draft'):
        raise ValidationError('Publish a draft or retire a programme; create a new version for revisions.')
    staff_at(obj.clinical_owner, obj.facility_id)
    obj.status = decision
    obj.reviewed_by, obj.reviewed_at, obj.review_reason = actor, timezone.now(), reason
    obj._history_user = actor
    obj.save()
    return obj


@transaction.atomic
def enroll(actor, **data):
    role(actor, ('admin', 'clinician'))
    patient = filter_by_facility(Patient.objects.select_for_update(), actor).filter(pk=data['patient'].pk).first()
    if not patient:
        raise PermissionDenied
    if patient.merged_into_id:
        raise ValidationError('Patient identity changed.')
    programme = scoped_lock(ProgrammeDefinition, data['programme'].pk, actor)
    staff_at(data['clinician'], patient.facility_id)
    if data['clinician'].role != 'clinician' or programme.status != 'published' or programme.facility_id != patient.facility_id:
        raise ValidationError('Use a published programme and clinician from this facility.')
    if data['enrolled_on'] > timezone.localdate() or data['next_review'] < data['enrolled_on']:
        raise ValidationError('Check enrollment and follow-up dates.')
    if ProgrammeEnrollment.objects.filter(patient=patient, programme__facility_id=programme.facility_id, programme__name=programme.name, status='active').exists():
        raise ValidationError('This patient already has an active enrollment in a version of this programme.')
    return save_valid(ProgrammeEnrollment(protocol_snapshot=f'{programme.name} v{programme.version}\nSource: {programme.source_reference}\n{programme.protocol}', **data), actor)


def locked_enrollment(pk, actor):
    role(actor, ('admin', 'clinician', 'nurse'))
    initial = ProgrammeEnrollment.objects.get(pk=pk)
    patient = filter_by_facility(Patient.objects.select_for_update(), actor).filter(pk=initial.patient_id).first()
    if not patient:
        raise PermissionDenied
    if patient.merged_into_id:
        raise ValidationError('Patient identity changed.')
    return ProgrammeEnrollment.objects.select_for_update().get(pk=pk)


@transaction.atomic
def programme_visit(pk, actor, **data):
    obj = locked_enrollment(pk, actor)
    if obj.status != 'active':
        raise ValidationError('Programme enrollment is closed.')
    if not obj.enrolled_on <= data['occurred_on'] <= timezone.localdate() or data['next_review'] < data['occurred_on']:
        raise ValidationError('Check review and next-review dates.')
    if data.get('amends') and data['amends'].enrollment_id != obj.pk:
        raise ValidationError('Amend a review from this enrollment.')
    latest = obj.reviews.order_by('-occurred_on', '-pk').first()
    if latest and data['occurred_on'] < latest.occurred_on and not data.get('amends'):
        raise ValidationError('Use an amendment reference for a backdated review.')
    if data.get('amends') and obj.reviews.filter(amends=data['amends']).exists():
        raise ValidationError('This note already has an amendment; amend the latest correction.')
    review = save_valid(ProgrammeReview(enrollment=obj, **data), actor)
    if not latest or data['occurred_on'] >= latest.occurred_on:
        obj.next_review = data['next_review']
    obj._history_user = actor
    obj.save()
    return review


@transaction.atomic
def programme_close(pk, actor, decision, reason):
    role(actor, ('admin', 'clinician'))
    obj = locked_enrollment(pk, actor)
    reason_required(reason)
    if decision not in ('completed', 'transferred', 'withdrawn'):
        raise ValidationError('Choose a supported closure outcome.')
    if obj.status == 'active':
        obj.status, obj.closure_reason, obj.closed_at = decision, reason, timezone.now()
        obj._history_user = actor
        obj.save()
    return obj


@transaction.atomic
def imaging_create(actor, **data):
    order = locked_order(data['order'].pk, actor)
    if order.order_type != 'imaging' or order.status == 'cancelled':
        raise ValidationError('Choose an active imaging order.')
    uid = data['study_uid']
    if not re.fullmatch(r'(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))+', uid) or len(uid) > 64:
        raise ValidationError('Study UID must contain dot-separated numeric components without leading zeros (maximum 64 characters).')
    if data['performed_at'] > timezone.now() or data['performed_at'] < order.created_at:
        raise ValidationError('Study time must be between order creation and now.')
    if data.get('viewer_url'):
        url = urlsplit(data['viewer_url'])
        try:
            allowed = url.scheme == 'https' and url.hostname in getattr(settings, 'PACS_VIEWER_ALLOWED_HOSTS', []) and url.port in (None, 443) and not url.username and not url.password and not url.fragment and not url.query
        except ValueError:
            allowed = False
        if not allowed:
            raise ValidationError('Use an approved HTTPS viewer host, without credentials, query tokens, fragments or custom ports.')
    return save_valid(ImagingStudy(**data), actor)
