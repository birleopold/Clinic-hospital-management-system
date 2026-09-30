"""Authored clinical documentation and reviewed operational evidence."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from .models import Record


class VaccinationCorrection(Record):
    vaccination = models.ForeignKey(
        "operations.Vaccination", on_delete=models.PROTECT, related_name="corrections"
    )
    field_name = models.CharField(
        max_length=32,
        choices=[
            (x, x.replace("_", " ").capitalize())
            for x in (
                "manufacturer",
                "lot_number",
                "expires_on",
                "dose",
                "route",
                "site",
                "administered_at",
                "note",
                "status",
            )
        ],
    )
    corrected_value = models.TextField(
        help_text="For status use entered_error; dates use YYYY-MM-DD and times include the timezone."
    )
    reason = models.TextField()
    original_value = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    applied_at = models.DateTimeField(null=True, blank=True)


class StorageProtocol(Record):
    facility = models.ForeignKey("accounts.Facility", on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    lower_c = models.DecimalField(max_digits=6, decimal_places=2)
    upper_c = models.DecimalField(max_digits=6, decimal_places=2)
    source_reference = models.CharField(
        max_length=250,
        help_text="Manufacturer/facility-approved storage specification and version.",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(lower_c__lt=models.F("upper_c")),
                name="storage_protocol_range",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.lower_c}–{self.upper_c} °C)"


class ColdChainReading(Record):
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT)
    protocol = models.ForeignKey(StorageProtocol, on_delete=models.PROTECT)
    measured_at = models.DateTimeField()
    temperature_c = models.DecimalField(max_digits=6, decimal_places=2)
    device_reference = models.CharField(max_length=120)
    note = models.TextField(blank=True)
    excursion = models.BooleanField(default=False)


class PerioperativeEntry(Record):
    case = models.ForeignKey(
        "operations.TheatreCase",
        on_delete=models.PROTECT,
        related_name="clinical_entries",
    )
    occurred_at = models.DateTimeField()
    kind = models.CharField(
        max_length=20,
        choices=[
            ("anesthesia", "Anesthesia record"),
            ("observation", "Intraoperative observation"),
            ("complication", "Complication"),
            ("handoff", "Handoff"),
        ],
    )
    findings = models.TextField()
    intervention = models.TextField()
    plan = models.TextField()
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendment",
    )
    amendment_reason = models.CharField(max_length=250, blank=True)


class InstrumentCount(Record):
    case = models.ForeignKey(
        "operations.TheatreCase",
        on_delete=models.PROTECT,
        related_name="instrument_counts",
    )
    phase = models.CharField(
        max_length=20,
        choices=[
            ("opening", "Opening"),
            ("closure", "Closure"),
            ("handoff", "Handoff"),
        ],
    )
    item_group = models.CharField(max_length=160)
    expected = models.PositiveIntegerField()
    counted = models.PositiveIntegerField()
    discrepancy_note = models.TextField(blank=True)
    resolution = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)


class Delivery(Record):
    pregnancy = models.OneToOneField(
        "operations.Pregnancy", on_delete=models.PROTECT, related_name="delivery"
    )
    occurred_at = models.DateTimeField()
    mode = models.CharField(
        max_length=120, help_text="Clinician-recorded method of delivery."
    )
    maternal_condition = models.TextField()
    complications = models.TextField(
        help_text="Record findings, or an explicit reviewed absence."
    )
    care_provided = models.TextField()
    follow_up_plan = models.TextField()

    def __str__(self):
        return f"Delivery #{self.pk}: {self.pregnancy.patient}"


class Newborn(Record):
    delivery = models.ForeignKey(
        Delivery, on_delete=models.PROTECT, related_name="newborns"
    )
    patient = models.OneToOneField(
        "demographics.Patient",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="birth_record",
        help_text="Register a separate patient identity for a live-born infant.",
    )
    birth_order = models.PositiveIntegerField(default=1)
    outcome = models.CharField(
        max_length=20,
        choices=[
            ("live_birth", "Live birth"),
            ("stillbirth", "Stillbirth"),
            ("other", "Other / clarify in notes"),
        ],
    )
    birth_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    apgar_1_min = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_5_min = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "birth_order"], name="unique_birth_order"
            ),
            models.CheckConstraint(
                condition=Q(birth_order__gte=1), name="positive_birth_order"
            ),
        ]


class LabourObservation(Record):
    pregnancy = models.ForeignKey(
        "operations.Pregnancy",
        on_delete=models.PROTECT,
        related_name="labour_observations",
    )
    observed_at = models.DateTimeField()
    fetal_heart_rate = models.PositiveIntegerField(null=True, blank=True)
    cervical_dilation_cm = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    contractions_per_10_min = models.PositiveSmallIntegerField(null=True, blank=True)
    maternal_pulse = models.PositiveIntegerField(null=True, blank=True)
    systolic = models.PositiveIntegerField(null=True, blank=True)
    diastolic = models.PositiveIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    findings = models.TextField()
    plan = models.TextField()
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendment",
    )
    amendment_reason = models.CharField(max_length=250, blank=True)


class RehabilitationOutcome(Record):
    plan = models.ForeignKey(
        "operations.RehabilitationPlan",
        on_delete=models.PROTECT,
        related_name="measurements",
    )
    measured_at = models.DateTimeField()
    instrument_name = models.CharField(max_length=160)
    instrument_version = models.CharField(max_length=80)
    source_reference = models.CharField(
        max_length=250,
        help_text="Approved instrument source/version and permission or licence reference.",
    )
    score = models.DecimalField(max_digits=12, decimal_places=3)
    units = models.CharField(max_length=80)
    interpretation = models.TextField(
        help_text="Clinician-authored interpretation; no automatic scoring or recommendations."
    )


class VaccinationAdverseEvent(Record):
    vaccination = models.ForeignKey(
        "operations.Vaccination",
        on_delete=models.PROTECT,
        related_name="adverse_events",
    )
    occurred_at = models.DateTimeField()
    description = models.TextField()
    seriousness = models.CharField(
        max_length=20,
        default="undetermined",
        choices=[
            ("undetermined", "Undetermined"),
            ("non_serious", "Non-serious"),
            ("serious", "Serious"),
        ],
        help_text="Staff assessment; this record does not establish causality.",
    )
    action_taken = models.TextField()
    follow_up_on = models.DateField(null=True, blank=True)
    reporting_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="External reporting reference, if reported. Saving does not submit a report.",
    )
    status = models.CharField(
        max_length=16,
        default="open",
        choices=[
            ("open", "Awaiting review"),
            ("reviewed", "Reviewed"),
            ("closed", "Closed"),
        ],
    )
    assessment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
