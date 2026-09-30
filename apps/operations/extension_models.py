"""Consent, traceability and governed clinical workflow extensions."""
from django.db import models
from django.db.models import Q, F
from .models import Record, PatientRecord


class ContactPreference(PatientRecord):
    patient=models.OneToOneField('demographics.Patient',on_delete=models.PROTECT,related_name='contact_preference')
    sms_allowed=models.BooleanField(default=False)
    verified_phone=models.CharField(max_length=20,blank=True)
    evidence=models.CharField(max_length=250)
    updated_at=models.DateTimeField(auto_now=True)


class ReminderAttempt(models.Model):
    reminder=models.ForeignKey('operations.Reminder',on_delete=models.PROTECT,related_name='delivery_attempts')
    started_at=models.DateTimeField(auto_now_add=True)
    ended_at=models.DateTimeField(null=True,blank=True)
    outcome=models.CharField(max_length=16,default='processing',choices=[('processing','In progress'),('accepted','Provider accepted'),('failed','Failed'),('review','Needs reconciliation')])
    provider_reference=models.CharField(max_length=160,blank=True)
    detail=models.CharField(max_length=250,blank=True)


class RecallOutreach(models.Model):
    recall=models.OneToOneField('operations.PatientRecall',on_delete=models.PROTECT)
    reminder=models.OneToOneField('operations.Reminder',null=True,blank=True,on_delete=models.PROTECT)
    escalation=models.OneToOneField('operations.WorkTask',null=True,blank=True,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)


class SpecimenCustody(Record):
    specimen=models.ForeignKey('operations.Specimen',on_delete=models.PROTECT,related_name='custody_events')
    event=models.CharField(max_length=20,choices=[('handoff','Sent / handed off'),('received','Received at destination'),('stored','Stored'),('referred','Referred externally'),('returned','External return'),('disposed','Disposed')])
    from_location=models.CharField(max_length=160)
    to_location=models.CharField(max_length=160)
    receiver=models.CharField(max_length=160)
    condition=models.CharField(max_length=250)
    reference=models.CharField(max_length=160)
    occurred_at=models.DateTimeField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['specimen','reference'],name='unique_specimen_event_reference')]


class SpecimenAliquot(Record):
    parent=models.ForeignKey('operations.Specimen',on_delete=models.PROTECT,related_name='aliquots')
    child=models.OneToOneField('operations.Specimen',on_delete=models.PROTECT,related_name='aliquot_origin')
    quantity=models.DecimalField(max_digits=10,decimal_places=3)
    unit=models.CharField(max_length=30)
    reason=models.CharField(max_length=250)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(quantity__gt=0)&~Q(parent=F('child')),name='valid_specimen_aliquot')]


class ReagentLot(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    name=models.CharField(max_length=120)
    lot_number=models.CharField(max_length=100)
    expires_on=models.DateField()
    opened_on=models.DateField(null=True,blank=True)
    use_by=models.DateField(null=True,blank=True)
    quarantined=models.BooleanField(default=True)
    review_reason=models.CharField(max_length=250,blank=True)
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','name','lot_number'],name='unique_reagent_lot')]
    def __str__(self):return f'{self.name} · {self.lot_number}'


class LaboratoryQC(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    asset=models.ForeignKey('operations.FacilityAsset',on_delete=models.PROTECT)
    reagent=models.ForeignKey(ReagentLot,on_delete=models.PROTECT)
    procedure_reference=models.CharField(max_length=250)
    control_lot=models.CharField(max_length=120)
    observations=models.TextField()
    outcome=models.CharField(max_length=12,choices=[('pass','Pass'),('fail','Fail')])
    valid_until=models.DateTimeField()
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)


class LabRunEvidence(Record):
    worksheet=models.OneToOneField('operations.DiagnosticWorksheet',on_delete=models.PROTECT,related_name='laboratory_run')
    qc=models.ForeignKey(LaboratoryQC,on_delete=models.PROTECT)
    run_at=models.DateTimeField()
    reference=models.CharField(max_length=160)


class ProgrammeDefinition(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    name=models.CharField(max_length=120)
    version=models.PositiveIntegerField()
    source_reference=models.CharField(max_length=250)
    protocol=models.TextField(help_text='Facility-approved programme workflow; no automatic eligibility, dosage or treatment decisions.')
    clinical_owner=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    status=models.CharField(max_length=12,default='draft',choices=[('draft','Draft'),('published','Published'),('retired','Retired')])
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','name','version'],name='unique_programme_version')]
    def __str__(self):return f'{self.name} v{self.version}'


class ProgrammeEnrollment(PatientRecord):
    programme=models.ForeignKey(ProgrammeDefinition,on_delete=models.PROTECT)
    protocol_snapshot=models.TextField()
    clinician=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    eligibility_evidence=models.TextField()
    consent_reference=models.CharField(max_length=250)
    enrolled_on=models.DateField()
    next_review=models.DateField()
    status=models.CharField(max_length=12,default='active',choices=[('active','Active'),('completed','Completed'),('transferred','Transferred'),('withdrawn','Withdrawn')])
    closure_reason=models.CharField(max_length=250,blank=True)
    closed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['patient','programme'],condition=Q(status='active'),name='unique_active_programme_enrollment')]
    def __str__(self):return f'#{self.pk} · {self.patient} · {self.programme}'


class ProgrammeReview(Record):
    enrollment=models.ForeignKey(ProgrammeEnrollment,on_delete=models.PROTECT,related_name='reviews')
    occurred_on=models.DateField()
    findings=models.TextField()
    plan=models.TextField()
    next_review=models.DateField()
    amends=models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT)


class ImagingStudy(Record):
    order=models.OneToOneField('orders.Order',on_delete=models.PROTECT,related_name='imaging_study')
    study_uid=models.CharField(max_length=64,unique=True)
    accession=models.CharField(max_length=100)
    modality=models.CharField(max_length=30)
    performed_at=models.DateTimeField()
    viewer_url=models.URLField(max_length=500,blank=True,help_text='Only an explicitly allowlisted HTTPS viewer host is permitted. The viewer must enforce its own patient authorization.')
    reference=models.CharField(max_length=250)
