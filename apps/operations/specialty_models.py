"""Specialty documentation; no generated clinical recommendations or dose schedules."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from .models import PatientRecord, Record


class TheatreCase(PatientRecord):
    room = models.ForeignKey("operations.ServiceRoom", on_delete=models.PROTECT)
    surgeon = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="theatre_cases"
    )
    procedure = models.CharField(max_length=200)
    indication = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        default="planned",
        choices=[
            ("planned", "Planned"),
            ("ready", "Ready"),
            ("in_progress", "In progress"),
            ("recovery", "Recovery"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
    )
    consent_reference = models.CharField(max_length=200, blank=True)
    checklist_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Reference to the completed, facility-approved preoperative checklist.",
    )
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    recovery_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="theatre_positive_duration",
            )
        ]

    def __str__(self):
        return f"#{self.pk}: {self.patient} — {self.procedure}"


class Pregnancy(PatientRecord):
    gravida = models.PositiveIntegerField(
        help_text="Recorded by the clinician, including this pregnancy."
    )
    parity = models.PositiveIntegerField()
    last_menstrual_period = models.DateField(null=True, blank=True)
    estimated_due_date = models.DateField(
        help_text="Clinician-confirmed date; not calculated automatically."
    )
    assessment = models.TextField()
    status = models.CharField(
        max_length=16,
        default="active",
        choices=[("active", "Active"), ("closed", "Closed")],
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=200, blank=True)
    closure_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient"],
                condition=Q(status="active"),
                name="one_active_pregnancy",
            ),
            models.CheckConstraint(
                condition=Q(gravida__gte=1, parity__lt=models.F("gravida")),
                name="valid_pregnancy_history",
            ),
        ]

    def __str__(self):
        return f"#{self.pk}: {self.patient} / due {self.estimated_due_date}"


class MaternityVisit(Record):
    pregnancy = models.ForeignKey(
        Pregnancy, on_delete=models.PROTECT, related_name="visits"
    )
    occurred_at = models.DateTimeField()
    visit_type = models.CharField(
        max_length=16,
        choices=[
            ("antenatal", "Antenatal"),
            ("delivery", "Delivery"),
            ("postnatal", "Postnatal"),
        ],
    )
    findings = models.TextField()
    care_provided = models.TextField()
    plan = models.TextField()
    follow_up_on = models.DateField(null=True, blank=True)
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendment",
    )
    amendment_reason = models.CharField(max_length=250, blank=True)


class Vaccination(PatientRecord):
    stock_source = models.CharField(
        max_length=16,
        default="external",
        choices=[
            ("external", "External / previously issued"),
            ("clinic", "Consume clinic stock"),
        ],
    )
    source_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="External provider or existing dispense/stock movement reference. Never deduct the same dose twice.",
    )
    stock_batch = models.ForeignKey(
        "inventory.Batch", null=True, blank=True, on_delete=models.PROTECT
    )
    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Base inventory units consumed, not the administered volume. Verify against the selected item.",
    )

    vaccine = models.CharField(max_length=160)
    dose_label = models.CharField(
        max_length=80,
        help_text="Clinician-selected dose or series label; no automatic schedule.",
    )
    due_on = models.DateField()
    status = models.CharField(
        max_length=16,
        default="scheduled",
        choices=[
            ("scheduled", "Scheduled"),
            ("given", "Given"),
            ("entered_error", "Entered in error"),
            ("deferred", "Deferred"),
            ("cancelled", "Cancelled"),
        ],
    )
    administered_at = models.DateTimeField(null=True, blank=True)
    administered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    manufacturer = models.CharField(max_length=120, blank=True)
    lot_number = models.CharField(max_length=100, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    dose = models.CharField(max_length=80, blank=True)
    route = models.CharField(max_length=80, blank=True)
    site = models.CharField(max_length=100, blank=True)
    consent_reference = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.patient}: {self.vaccine} / {self.dose_label}"


class RehabilitationPlan(PatientRecord):
    clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rehabilitation_plans",
    )
    problem = models.CharField(max_length=200)
    baseline = models.TextField()
    goals = models.TextField()
    intervention_plan = models.TextField()
    review_on = models.DateField()
    status = models.CharField(
        max_length=16,
        default="active",
        choices=[
            ("active", "Active"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
    )
    outcome = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"#{self.pk}: {self.patient} / {self.problem}"


class RehabilitationSession(Record):
    plan = models.ForeignKey(
        RehabilitationPlan, on_delete=models.PROTECT, related_name="sessions"
    )
    occurred_at = models.DateTimeField()
    intervention = models.TextField()
    response = models.TextField()
    progress = models.TextField()
    next_visit_on = models.DateField(null=True, blank=True)
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendment",
    )
    amendment_reason = models.CharField(max_length=250, blank=True)
