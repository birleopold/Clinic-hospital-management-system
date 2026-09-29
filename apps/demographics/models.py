from django.db import models
from simple_history.models import HistoricalRecords

class Patient(models.Model):
    M = 'M'
    F = 'F'
    O = 'O'
    GENDER_CHOICES = [
        (M, 'Male'),
        (F, 'Female'),
        (O, 'Other'),
    ]

    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64)
    other_names = models.CharField(max_length=128, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    insurance_provider = models.CharField(max_length=128, blank=True)
    insurance_id = models.CharField(max_length=64, blank=True)
    facility = models.ForeignKey(
        'accounts.Facility',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='patients',
    )
    consent_data_processing = models.BooleanField(
        default=False,
        help_text='Patient consents to processing of personal data for care and billing (DPPA-style record).',
    )
    consent_recorded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When consent was last recorded as granted.',
    )
    data_retention_until = models.DateField(
        null=True,
        blank=True,
        help_text='Optional policy date after which inactive records may be archived or deleted per clinic SOP.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()
