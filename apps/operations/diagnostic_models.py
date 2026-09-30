import uuid
from django.db import models
from django.db.models import Q, F
from .models import Record


class VisitingSpecialist(Record):
    user=models.OneToOneField('accounts.User',on_delete=models.PROTECT,related_name='visiting_specialist')
    specialty=models.CharField(max_length=120)
    credential_reference=models.CharField(max_length=200)
    credential_expires=models.DateField()
    verification_note=models.TextField()


class VisitingEngagement(Record):
    specialist=models.ForeignKey(VisitingSpecialist,on_delete=models.PROTECT)
    case=models.ForeignKey('operations.TheatreCase',on_delete=models.PROTECT,related_name='visiting_engagements')
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    purpose=models.CharField(max_length=250)
    revoked_at=models.DateTimeField(null=True,blank=True)
    revoke_reason=models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')),name='visiting_positive_interval')]


class VisitingCaseNote(Record):
    engagement=models.ForeignKey(VisitingEngagement,on_delete=models.PROTECT,related_name='notes')
    body=models.TextField()
    amends=models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT)


class DiagnosticTemplate(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    name=models.CharField(max_length=120)
    version=models.PositiveIntegerField()
    order_type=models.CharField(max_length=16,choices=[('lab','Lab'),('imaging','Imaging'),('procedure','Other diagnostic procedure')])
    modality=models.CharField(max_length=30,blank=True,help_text='For example X-ray, CT, ultrasound or MRI. This is an operational label, not a device connection.')
    patient_instructions=models.TextField(blank=True,help_text='Facility-approved patient preparation instructions; never generated automatically.')
    instruction_language=models.CharField(max_length=40,blank=True)
    instruction_reference=models.CharField(max_length=250,blank=True)
    fields=models.JSONField(help_text='A list of fields with key, label, type (text/number/choice), required, unit, reference and choices where applicable.')
    status=models.CharField(max_length=12,default='draft',choices=[('draft','Draft'),('published','Published'),('retired','Retired')])
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','name','version'],name='unique_diagnostic_template_version')]
    def __str__(self):return f'{self.name} v{self.version}'


class DiagnosticWorkItem(Record):
    order=models.OneToOneField('orders.Order',on_delete=models.PROTECT,related_name='diagnostic_work')
    operator=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    room=models.ForeignKey('operations.ServiceRoom',null=True,blank=True,on_delete=models.PROTECT)
    asset=models.ForeignKey('operations.FacilityAsset',null=True,blank=True,on_delete=models.PROTECT)
    duration_minutes=models.PositiveSmallIntegerField(default=30)
    instruction_template=models.ForeignKey('operations.DiagnosticTemplate',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    instructions_snapshot=models.JSONField(default=dict,blank=True)
    instructions_acknowledged_at=models.DateTimeField(null=True,blank=True)
    instructions_acknowledged_grant=models.ForeignKey('operations.PortalGrant',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    modality=models.CharField(max_length=30,blank=True)
    scheduled_at=models.DateTimeField(null=True,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    preparation_note=models.CharField(max_length=250,blank=True,help_text='Record the approved preparation/checklist reference. Do not infer medical clearance.')
    revision=models.PositiveIntegerField(default=1)


class DiagnosticWorksheet(Record):
    result=models.OneToOneField('orders.OrderResult',on_delete=models.PROTECT,related_name='worksheet')
    template=models.ForeignKey(DiagnosticTemplate,on_delete=models.PROTECT)
    snapshot=models.JSONField()
    answers=models.JSONField()
    request_key=models.UUIDField(default=uuid.uuid4,unique=True)
    withdrawn_at=models.DateTimeField(null=True,blank=True)
    withdrawal_reason=models.CharField(max_length=250,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
