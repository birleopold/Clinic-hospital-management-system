"""Facility-scoped specialty operations with row-locked transitions and history."""

from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from common.facility_scope import filter_by_facility
from apps.accounts.models import User
from apps.demographics.models import Patient
from .models import (
    ServiceRoom,
    TheatreCase,
    Pregnancy,
    MaternityVisit,
    Vaccination,
    RehabilitationPlan,
    RehabilitationSession,
)

SPECIALTIES = (
    TheatreCase,
    Pregnancy,
    MaternityVisit,
    Vaccination,
    RehabilitationPlan,
    RehabilitationSession,
)


def authorize(actor, patient, roles=("clinician", "nurse")):
    if not actor.is_active or not (
        actor.is_superuser or actor.role == "admin" or actor.role in roles
    ):
        raise PermissionDenied
    if not filter_by_facility(Patient.objects.filter(pk=patient.pk), actor).exists():
        raise PermissionDenied
    if patient.merged_into_id:
        raise ValidationError("Select the canonical patient identity.")


def check_staff(user, patient):
    if (
        not user.is_active
        or user.role != "clinician"
        or not User.objects.filter(
            pk=user.pk, staff_profile__facility_id=patient.facility_id
        ).exists()
    ):
        raise ValidationError(
            "Select an active clinician assigned to the patient facility."
        )


def check_theatre_conflicts(obj):
    if obj.ends_at <= obj.starts_at:
        raise ValidationError("The planned end must be after the start.")
    if obj.room.facility_id != obj.patient.facility_id:
        raise ValidationError(
            "Theatre room and patient must belong to the same facility."
        )
    # Deterministic resource locks serialize competing room/surgeon bookings.
    User.objects.select_for_update().get(pk=obj.surgeon_id)
    ServiceRoom.objects.select_for_update().get(pk=obj.room_id)
    check_staff(obj.surgeon, obj.patient)
    clashes = (
        TheatreCase.objects.exclude(pk=obj.pk)
        .exclude(status__in=["cancelled", "completed"])
        .filter(starts_at__lt=obj.ends_at, ends_at__gt=obj.starts_at)
        .filter(
            Q(room_id=obj.room_id)
            | Q(surgeon_id=obj.surgeon_id)
            | Q(patient_id=obj.patient_id)
        )
    )
    from apps.appointments.models import Appointment, DoctorTimeOff

    appointments = (
        Appointment.objects.exclude(status__in=["cancelled", "no_show"])
        .filter(
            scheduled_for__lt=obj.ends_at,
            scheduled_for__gt=obj.starts_at - timedelta(days=1),
        )
        .filter(
            Q(clinician_id=obj.surgeon_id)
            | Q(room_id=obj.room_id)
            | Q(patient_id=obj.patient_id)
        )
    )
    if any(
        a.scheduled_for + timedelta(minutes=a.duration_minutes) > obj.starts_at
        for a in appointments
    ):
        raise ValidationError(
            "The surgeon or room has an overlapping outpatient appointment."
        )
    if DoctorTimeOff.objects.filter(
        clinician_id=obj.surgeon_id, start__lt=obj.ends_at, end__gt=obj.starts_at
    ).exists():
        raise ValidationError("The surgeon is unavailable during this booking.")
    if clashes.exists():
        raise ValidationError(
            "Patient, surgeon or room already has an overlapping theatre booking."
        )


@transaction.atomic
def create_specialty(obj, actor):
    if not isinstance(obj, SPECIALTIES) or not obj._state.adding:
        raise ValidationError(
            "Use the documented transition or an amendment for existing records."
        )
    if isinstance(obj, MaternityVisit):
        obj.pregnancy = Pregnancy.objects.select_for_update().get(pk=obj.pregnancy_id)
        patient = obj.pregnancy.patient
    elif isinstance(obj, RehabilitationSession):
        obj.plan = RehabilitationPlan.objects.select_for_update().get(pk=obj.plan_id)
        patient = obj.plan.patient
    else:
        patient = obj.patient
    patient = Patient.objects.select_for_update().get(pk=patient.pk)
    authorize(actor, patient)
    if isinstance(obj, TheatreCase):
        obj.status = "planned"
        check_theatre_conflicts(obj)
    elif isinstance(obj, Pregnancy):
        obj.status = "active"
        if obj.last_menstrual_period and (
            obj.last_menstrual_period > timezone.localdate()
            or obj.estimated_due_date <= obj.last_menstrual_period
        ):
            raise ValidationError("Check the menstrual-period and estimated due dates.")
    elif isinstance(obj, RehabilitationPlan):
        obj.status = "active"
        check_staff(obj.clinician, patient)
    elif isinstance(obj, Vaccination):
        obj.status = "scheduled"
    elif isinstance(obj, (MaternityVisit, RehabilitationSession)):
        if obj.occurred_at > timezone.now():
            raise ValidationError(
                "A completed visit cannot be documented in the future."
            )
        if isinstance(obj, MaternityVisit):
            if (
                obj.pregnancy.status != "active"
                and obj.visit_type != "postnatal"
                and not obj.supersedes_id
            ):
                raise ValidationError(
                    "Only postnatal visits or amendments can be added to a closed pregnancy."
                )
            parent_field = "pregnancy_id"
        else:
            if obj.plan.status != "active" and not obj.supersedes_id:
                raise ValidationError("This rehabilitation plan is closed.")
            parent_field = "plan_id"
        followup = (
            obj.follow_up_on if isinstance(obj, MaternityVisit) else obj.next_visit_on
        )
        if followup and followup < timezone.localdate(obj.occurred_at):
            raise ValidationError("Follow-up cannot precede the recorded visit.")
        if obj.supersedes_id:
            prior = type(obj).objects.select_for_update().get(pk=obj.supersedes_id)
            if (
                getattr(prior, parent_field) != getattr(obj, parent_field)
                or not obj.amendment_reason.strip()
            ):
                raise ValidationError("Amendments need the same episode and a reason.")
    obj.created_by = actor
    obj._history_user = actor
    obj.full_clean()
    obj.save()
    return obj


def required(data, key):
    value = data.get(key, "").strip()
    if not value:
        raise ValidationError(f'{key.replace("_", " ").capitalize()} is required.')
    return value


@transaction.atomic
def transition_specialty(model, pk, operation, data, actor):
    if model not in (TheatreCase, Pregnancy, RehabilitationPlan, Vaccination):
        raise ValidationError("Visit records are amended by adding a new record.")
    obj = model.objects.select_for_update().get(pk=pk)
    authorize(actor, obj.patient)
    now = timezone.now()
    if isinstance(obj, TheatreCase):
        transitions = {
            "planned": ["ready", "cancelled"],
            "ready": ["in_progress", "cancelled"],
            "in_progress": ["recovery"],
            "recovery": ["completed"],
        }
        if operation not in transitions.get(obj.status, []):
            raise ValidationError("This theatre transition is no longer available.")
        if operation == "ready":
            obj.consent_reference = required(data, "consent_reference")
            obj.checklist_reference = required(data, "checklist_reference")
            obj.checked_by, obj.checked_at = actor, now
        elif operation == "in_progress":
            authorize(actor, obj.patient, ("clinician",))
            check_staff(obj.surgeon, obj.patient)
            User.objects.select_for_update().get(pk=obj.surgeon_id)
            ServiceRoom.objects.select_for_update().get(pk=obj.room_id)
            if (
                TheatreCase.objects.exclude(pk=obj.pk)
                .filter(status="in_progress")
                .filter(
                    Q(room_id=obj.room_id)
                    | Q(surgeon_id=obj.surgeon_id)
                    | Q(patient_id=obj.patient_id)
                )
                .exists()
            ):
                raise ValidationError(
                    "Patient, surgeon or room is still in an active procedure."
                )
            obj.started_at = now
        elif operation == "recovery":
            obj.outcome_note = required(data, "note")
            obj.recovery_at = now
        elif operation == "completed":
            obj.outcome_note += "\nRecovery handoff: " + required(data, "note")
            obj.completed_at = now
        else:
            obj.outcome_note = required(data, "note")
            obj.completed_at = now
        obj.status = operation
    elif isinstance(obj, Pregnancy):
        if obj.status != "active" or operation != "close":
            raise ValidationError(
                "This pregnancy episode is already closed or the action is invalid."
            )
        obj.outcome = required(data, "outcome")
        obj.closure_note = required(data, "note")
        obj.status, obj.closed_at = "closed", now
    elif isinstance(obj, RehabilitationPlan):
        if obj.status != "active" or operation not in ("completed", "cancelled"):
            raise ValidationError("This plan is closed or the action is invalid.")
        obj.outcome = required(data, "note")
        obj.status, obj.completed_at = operation, now
    elif isinstance(obj, Vaccination):
        if obj.status not in ("scheduled", "deferred") or operation not in (
            "given",
            "deferred",
            "cancelled",
            "scheduled",
        ):
            raise ValidationError("This vaccination is final or the action is invalid.")
        if operation == "given":
            from django import forms

            for key in (
                "manufacturer",
                "lot_number",
                "dose",
                "route",
                "site",
                "consent_reference",
            ):
                setattr(obj, key, required(data, key))
            obj.administered_at = forms.DateTimeField().clean(
                required(data, "administered_at")
            )
            obj.expires_on = forms.DateField().clean(required(data, "expires_on"))
            if obj.administered_at > now or obj.expires_on < timezone.localdate(
                obj.administered_at
            ):
                raise ValidationError(
                    "Administration cannot be future-dated or use an expired lot."
                )
            if (
                obj.patient.date_of_birth
                and timezone.localdate(obj.administered_at) < obj.patient.date_of_birth
            ):
                raise ValidationError(
                    "Administration cannot precede the patient birth date."
                )
            obj.administered_by = actor
            obj.note = data.get("note", "").strip()
        else:
            obj.note = required(data, "note")
            if operation == "scheduled":
                from django import forms

                obj.due_on = forms.DateField().clean(required(data, "due_on"))
        obj.status = operation
    else:
        raise ValidationError("Unsupported specialty action.")
    obj._history_user = actor
    obj.full_clean()
    obj.save()
    return obj
