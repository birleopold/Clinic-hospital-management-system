import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords

class Record(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    history = HistoricalRecords(inherit=True)
    class Meta:
        abstract = True

class PatientRecord(Record):
    patient = models.ForeignKey('demographics.Patient', on_delete=models.PROTECT)
    class Meta:
        abstract = True

class ClinicalEntry(PatientRecord):
    KINDS = [('allergy','Allergy'),('problem','Chronic problem'),('medication','Medication history'),('note','Signed clinical note')]
    kind = models.CharField(max_length=16, choices=KINDS)
    text = models.TextField()
    supersedes = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    def __str__(self):
        return f'{self.get_kind_display()}: {self.text[:60]}'

class Referral(PatientRecord):
    destination = models.CharField(max_length=200)
    reason = models.TextField()
    due_date = models.DateField()
    status = models.CharField(max_length=16, default='open', choices=[('open','Open'),('accepted','Accepted'),('completed','Completed'),('cancelled','Cancelled')])
    completed_at = models.DateTimeField(null=True, blank=True)

class Specimen(Record):
    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT, related_name='specimens')
    accession = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    specimen_type = models.CharField(max_length=100)
    status = models.CharField(max_length=16, default='collected', choices=[('collected','Collected'),('received','Received'),('rejected','Rejected')])
    rejection_reason = models.CharField(max_length=250, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

class StockLocation(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['facility','name'], name='unique_stock_location')]
    def __str__(self):
        return f'{self.facility} / {self.name}'

class StockCount(Record):
    batch = models.ForeignKey('inventory.Batch', on_delete=models.PROTECT)
    expected = models.DecimalField(max_digits=12, decimal_places=2)
    counted = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=16, default='draft', choices=[('draft','Draft'),('posted','Posted')])
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')

class Refund(Record):
    approved_at = models.DateTimeField(null=True, blank=True)
    payment = models.ForeignKey('billing.Payment', on_delete=models.PROTECT, related_name='refunds')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=16, default='requested', choices=[('requested','Requested'),('approved','Approved')])
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    cash_session = models.ForeignKey('billing.CashSession', null=True, on_delete=models.PROTECT)

class Bed(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    ward = models.CharField(max_length=100)
    name = models.CharField(max_length=60)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['facility','ward','name'], name='unique_ward_bed')]
    def __str__(self):
        return f'{self.ward} / {self.name}'

class Admission(PatientRecord):
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT)
    reason = models.TextField()
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharge_summary = models.TextField(blank=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['bed'], condition=Q(discharged_at__isnull=True), name='one_active_bed_occupant'),
            models.UniqueConstraint(fields=['patient'], condition=Q(discharged_at__isnull=True), name='one_active_admission'),
        ]

class NursingObservation(Record):
    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name='observations')
    observations = models.TextField()

class MedicationAdministration(Record):
    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name='administrations')
    prescription_item = models.ForeignKey('pharmacy.PrescriptionItem', on_delete=models.PROTECT)
    scheduled_for = models.DateTimeField()
    outcome = models.CharField(max_length=16, choices=[('given','Given'),('withheld','Withheld'),('refused','Refused')])
    dose = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['admission','prescription_item','scheduled_for'], name='one_administration_per_dose')]

class PortalGrant(PatientRecord):
    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

class Payer(models.Model):
    name = models.CharField(max_length=160)
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    contact = models.CharField(max_length=160, blank=True)
    def __str__(self):
        return self.name

class Claim(Record):
    invoice = models.ForeignKey('billing.Invoice', on_delete=models.PROTECT)
    payer = models.ForeignKey(Payer, on_delete=models.PROTECT)
    membership_number = models.CharField(max_length=100)
    authorization_reference = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, default='draft', choices=[('draft','Draft'),('submitted','Submitted'),('accepted','Accepted'),('rejected','Rejected')])
    response_note = models.TextField(blank=True)


class Reminder(PatientRecord):
    scheduled_for = models.DateTimeField()
    body = models.CharField(max_length=320, default='You have an upcoming clinic appointment. Please contact reception for details.')
    consent_confirmed = models.BooleanField(default=False)
    status = models.CharField(max_length=16, default='pending', choices=[('pending','Pending'),('processing','Processing'),('sent','Sent'),('failed','Failed'),('cancelled','Cancelled')])
    attempts = models.PositiveIntegerField(default=0)
    provider_reference = models.CharField(max_length=160, blank=True)
    last_error = models.CharField(max_length=250, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

class DuplicateReview(Record):
    patient = models.ForeignKey('demographics.Patient', on_delete=models.PROTECT, related_name='duplicate_reviews')
    candidate = models.ForeignKey('demographics.Patient', on_delete=models.PROTECT, related_name='+')
    reason = models.TextField()
    status = models.CharField(max_length=16, default='pending', choices=[('pending','Pending'),('confirmed','Same person'),('distinct','Different people')])
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)


class ServiceRoom(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['facility','name'], name='unique_service_room')]
    def __str__(self):
        return self.name


class InvoiceCredit(Record):
    invoice = models.ForeignKey('billing.Invoice', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=16, default='requested', choices=[('requested','Requested'),('approved','Approved')])
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
