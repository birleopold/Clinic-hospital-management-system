from decimal import Decimal
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from common.facility_scope import filter_by_facility
from apps.accounts.models import Facility
from apps.demographics.models import Patient
from apps.inventory.models import Batch, StockMovement
from .models import (
    Vaccination,
    VaccinationCorrection,
    VaccinationAdverseEvent,
    StorageProtocol,
    ColdChainReading,
    TheatreCase,
    PerioperativeEntry,
    InstrumentCount,
    Pregnancy,
    Delivery,
    Newborn,
    LabourObservation,
    RehabilitationPlan,
    RehabilitationOutcome,
)
from .specialty_services import authorize, required

CARE_RECORDS = (
    VaccinationCorrection,
    VaccinationAdverseEvent,
    StorageProtocol,
    ColdChainReading,
    PerioperativeEntry,
    InstrumentCount,
    Delivery,
    Newborn,
    LabourObservation,
    RehabilitationOutcome,
)


def facility_access(actor, facility_id, roles):
    if not actor.is_active or not (
        actor.is_superuser or actor.role == "admin" or actor.role in roles
    ):
        raise PermissionDenied
    if not filter_by_facility(
        Facility.objects.filter(pk=facility_id), actor, field="pk"
    ).exists():
        raise PermissionDenied


def correction_value(record, field_name, value):
    if field_name == "status":
        if value != "entered_error":
            raise ValidationError("A status correction can only mark entered_error.")
        return value
    if field_name not in dict(
        VaccinationCorrection._meta.get_field("field_name").choices
    ):
        raise ValidationError("Unsupported correction field.")
    field = Vaccination._meta.get_field(field_name)
    if field_name == "administered_at":
        return forms.DateTimeField().clean(value)
    if field_name == "expires_on":
        return forms.DateField().clean(value)
    return field.clean(value, record)


@transaction.atomic
def create_care_record(obj, actor):
    if not isinstance(obj, CARE_RECORDS) or not obj._state.adding:
        raise ValidationError("Use a reviewed correction or a new observation.")
    if isinstance(obj, StorageProtocol):
        facility_access(actor, obj.facility_id, ("store", "manager"))
    elif isinstance(obj, ColdChainReading):
        obj.batch = Batch.objects.select_for_update().get(pk=obj.batch_id)
        facility_access(
            actor,
            getattr(obj.batch.location, "facility_id", None),
            ("store", "manager", "nurse", "pharmacy"),
        )
        obj.protocol = StorageProtocol.objects.select_for_update().get(
            pk=obj.protocol_id
        )
        if (
            not obj.protocol.approved_at
            or obj.protocol.facility_id != obj.batch.location.facility_id
        ):
            raise ValidationError(
                "Choose an approved storage protocol for this facility."
            )
        if obj.measured_at > timezone.now():
            raise ValidationError("Cannot record a future temperature reading.")
        obj.excursion = (
            not obj.protocol.lower_c <= obj.temperature_c <= obj.protocol.upper_c
        )
        if obj.excursion:
            obj.batch.quarantined = True
            obj.batch.save(update_fields=["quarantined"])
            StockMovement.objects.create(
                item=obj.batch.item,
                batch=obj.batch,
                direction="adjust",
                quantity=0,
                reason="cold-chain quarantine",
                ref=f"temperature:user:{actor.pk}",
            )
    else:
        if isinstance(obj, VaccinationAdverseEvent):
            obj.vaccination = Vaccination.objects.select_for_update().get(
                pk=obj.vaccination_id
            )
            patient = obj.vaccination.patient
            if (
                obj.vaccination.status != "given"
                or obj.occurred_at < obj.vaccination.administered_at
            ):
                raise ValidationError(
                    "Choose a given vaccination preceding the reported event."
                )
            if obj.follow_up_on and obj.follow_up_on < timezone.localdate(
                obj.occurred_at
            ):
                raise ValidationError("Follow-up cannot precede the reported event.")
        elif isinstance(obj, VaccinationCorrection):
            obj.vaccination = Vaccination.objects.select_for_update().get(
                pk=obj.vaccination_id
            )
            patient = obj.vaccination.patient
            if obj.vaccination.status != "given":
                raise ValidationError("Only a given vaccination can be corrected.")
            correction_value(obj.vaccination, obj.field_name, obj.corrected_value)
            obj.original_value = str(getattr(obj.vaccination, obj.field_name))
        elif isinstance(obj, (PerioperativeEntry, InstrumentCount)):
            obj.case = TheatreCase.objects.select_for_update().get(pk=obj.case_id)
            patient = obj.case.patient
            if obj.case.status == "cancelled":
                raise ValidationError("This theatre case was cancelled.")
            if isinstance(obj, InstrumentCount):
                if obj.case.status == "completed":
                    raise ValidationError("This case is complete.")
                if obj.expected != obj.counted and not obj.discrepancy_note.strip():
                    raise ValidationError("Explain the count discrepancy.")
        elif isinstance(obj, (Delivery, LabourObservation)):
            obj.pregnancy = Pregnancy.objects.select_for_update().get(
                pk=obj.pregnancy_id
            )
            patient = obj.pregnancy.patient
        elif isinstance(obj, Newborn):
            obj.delivery = Delivery.objects.select_for_update().get(pk=obj.delivery_id)
            patient = obj.delivery.pregnancy.patient
            if obj.outcome == "live_birth" and not obj.patient_id:
                raise ValidationError(
                    "Register and select a separate patient for this live-born infant."
                )
            if obj.patient_id:
                baby = Patient.objects.select_for_update().get(pk=obj.patient_id)
                if (
                    baby.pk == patient.pk
                    or baby.facility_id != patient.facility_id
                    or baby.merged_into_id
                ):
                    raise ValidationError(
                        "Choose a separate canonical infant identity in this facility."
                    )
                if baby.date_of_birth != timezone.localdate(obj.delivery.occurred_at):
                    raise ValidationError(
                        "Infant birth date must match the delivery date."
                    )
            if obj.birth_weight_kg is not None and obj.birth_weight_kg <= 0:
                raise ValidationError("Birth weight must be positive.")
            if any(
                v is not None and not 0 <= v <= 10
                for v in (obj.apgar_1_min, obj.apgar_5_min)
            ):
                raise ValidationError("Recorded Apgar totals must be between 0 and 10.")
        else:
            obj.plan = RehabilitationPlan.objects.select_for_update().get(
                pk=obj.plan_id
            )
            patient = obj.plan.patient
        authorize(actor, patient)
        timestamp = next(
            (
                getattr(obj, n)
                for n in ("occurred_at", "observed_at", "measured_at")
                if hasattr(obj, n)
            ),
            None,
        )
        if timestamp and timestamp > timezone.now():
            raise ValidationError(
                "Cannot document a completed observation in the future."
            )
        if isinstance(obj, LabourObservation):
            if (
                obj.cervical_dilation_cm is not None
                and not 0 <= obj.cervical_dilation_cm <= 10
            ):
                raise ValidationError(
                    "Dilation must be recorded in centimetres, from 0 to 10."
                )
            if (
                obj.contractions_per_10_min is not None
                and obj.contractions_per_10_min > 10
            ):
                raise ValidationError("Check the contraction count per ten minutes.")
        if (
            isinstance(obj, (PerioperativeEntry, LabourObservation))
            and obj.supersedes_id
        ):
            prior = type(obj).objects.select_for_update().get(pk=obj.supersedes_id)
            key = "case_id" if isinstance(obj, PerioperativeEntry) else "pregnancy_id"
            if (
                getattr(obj, key) != getattr(prior, key)
                or not obj.amendment_reason.strip()
            ):
                raise ValidationError(
                    "Amendments require the same episode and a reason."
                )
    obj.created_by = actor
    obj._history_user = actor
    obj.full_clean()
    obj.save()
    return obj


@transaction.atomic
def review_care_record(model, pk, operation, data, actor):
    obj = model.objects.select_for_update().get(pk=pk)
    if isinstance(obj, VaccinationAdverseEvent):
        authorize(actor, obj.vaccination.patient, ("clinician",))
        if operation == "approve" and obj.status == "open":
            obj.assessment = required(data, "assessment")
            obj.status = "reviewed"
            obj.reviewed_by = actor
            obj.reviewed_at = timezone.now()
        elif operation == "close" and obj.status == "reviewed":
            obj.assessment += "\nFollow-up outcome: " + required(data, "assessment")
            obj.status = "closed"
            obj.closed_at = timezone.now()
        else:
            raise ValidationError("Invalid adverse-event transition.")
        obj._history_user = actor
        obj.full_clean()
        obj.save()
        return obj
    if operation != "approve" or model not in (
        StorageProtocol,
        VaccinationCorrection,
        InstrumentCount,
    ):
        raise ValidationError("This record has no review action.")
    if isinstance(obj, StorageProtocol):
        facility_access(actor, obj.facility_id, ("manager",))
        if obj.approved_at:
            return obj
        if obj.created_by_id == actor.pk:
            raise ValidationError("A different reviewer must approve this protocol.")
        obj.approved_by = actor
        obj.approved_at = timezone.now()
    elif isinstance(obj, InstrumentCount):
        obj.case = TheatreCase.objects.select_for_update().get(pk=obj.case_id)
        authorize(actor, obj.case.patient)
        if obj.verified_at:
            return obj
        if obj.created_by_id == actor.pk:
            raise ValidationError("A second staff member must verify the count.")
        if obj.expected != obj.counted:
            obj.resolution = required(data, "resolution")
        obj.verified_by = actor
        obj.verified_at = timezone.now()
    else:
        obj.vaccination = Vaccination.objects.select_for_update().get(
            pk=obj.vaccination_id
        )
        authorize(actor, obj.vaccination.patient, ("clinician",))
        if obj.applied_at:
            return obj
        if obj.created_by_id == actor.pk:
            raise ValidationError("A different clinician must review this correction.")
        if (
            obj.vaccination.status != "given"
            or str(getattr(obj.vaccination, obj.field_name)) != obj.original_value
        ):
            raise ValidationError(
                "The original record changed; review it and submit a fresh correction."
            )
        setattr(
            obj.vaccination,
            obj.field_name,
            correction_value(obj.vaccination, obj.field_name, obj.corrected_value),
        )
        v = obj.vaccination
        if v.administered_at > timezone.now() or v.expires_on < timezone.localdate(
            v.administered_at
        ):
            raise ValidationError("The corrected dates are inconsistent.")
        if (
            v.patient.date_of_birth
            and timezone.localdate(v.administered_at) < v.patient.date_of_birth
        ):
            raise ValidationError("Administration cannot precede the birth date.")
        v._history_user = actor
        v.full_clean()
        v.save()
        # Documentation corrections never imply physical stock was returned.
        obj.approved_by = actor
        obj.applied_at = timezone.now()
    obj._history_user = actor
    obj.full_clean()
    obj.save()
    return obj


def consume_vaccine_stock(vaccination):
    """Called inside the row-locked administration transaction, exactly once."""
    if vaccination.stock_source == "external":
        if vaccination.stock_batch_id or vaccination.stock_quantity:
            raise ValidationError(
                "External/previously issued doses must not select stock to deduct."
            )
        if not vaccination.source_reference.strip():
            raise ValidationError(
                "Record the external provider or previous dispense reference."
            )
        return
    if (
        not vaccination.stock_batch_id
        or not vaccination.stock_quantity
        or vaccination.stock_quantity <= 0
    ):
        raise ValidationError(
            "Select the vaccine batch and a positive base-unit quantity."
        )
    batch = Batch.objects.select_for_update().get(pk=vaccination.stock_batch_id)
    if (
        not batch.location_id
        or batch.location.facility_id != vaccination.patient.facility_id
    ):
        raise ValidationError("The stock batch belongs to another facility.")
    if (
        batch.quarantined
        or not batch.expiry
        or batch.expiry < timezone.localdate()
        or batch.quantity_on_hand < vaccination.stock_quantity
    ):
        raise ValidationError(
            "Batch is expired, quarantined, missing expiry or insufficient."
        )
    if (
        batch.batch_no != vaccination.lot_number
        or batch.expiry != vaccination.expires_on
    ):
        raise ValidationError(
            "Recorded lot number and expiry must match the selected stock batch."
        )
    batch.quantity_on_hand -= vaccination.stock_quantity
    batch.save(update_fields=["quantity_on_hand"])
    StockMovement.objects.create(
        item=batch.item,
        batch=batch,
        direction="out",
        quantity=vaccination.stock_quantity,
        reason="vaccination",
        ref=f"vaccination:{vaccination.pk}",
    )
