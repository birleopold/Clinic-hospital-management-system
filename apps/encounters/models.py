from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

class Encounter(models.Model):
    OPEN = 'open'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (OPEN, 'Open'),
        (CLOSED, 'Closed'),
    ]

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    facility = models.ForeignKey(
        'accounts.Facility',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='encounters',
    )
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=OPEN)
    chief_complaint = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        if self.facility_id is None and self.patient_id:
            patient = self.patient
            if patient.facility_id:
                self.facility_id = patient.facility_id
        if self.facility_id is None and self.clinician_id:
            sp = getattr(self.clinician, 'staff_profile', None)
            if sp and sp.facility_id:
                self.facility_id = sp.facility_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Encounter {self.id} - {self.patient} ({self.status})"

class Vital(models.Model):
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name='vitals')
    taken_at = models.DateTimeField(auto_now_add=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pulse = models.PositiveIntegerField(null=True, blank=True)
    systolic = models.PositiveIntegerField(null=True, blank=True)
    diastolic = models.PositiveIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True)
    spo2 = models.PositiveIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    history = HistoricalRecords()

class Diagnosis(models.Model):
    ICD10 = 'ICD10'
    WHO_MOH = 'WHO_MOH'
    LOCAL = 'LOCAL'
    CODING_SYSTEM_CHOICES = [
        (ICD10, 'ICD-10'),
        (WHO_MOH, 'WHO / MoH coded (e.g. HMIS condition list)'),
        (LOCAL, 'Local clinic code'),
    ]

    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name='diagnoses')
    code = models.CharField(max_length=16)
    coding_system = models.CharField(
        max_length=16,
        choices=CODING_SYSTEM_CHOICES,
        default=ICD10,
        help_text='Code list used for HMIS / MoH reporting alignment.',
    )
    description = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    history = HistoricalRecords()
