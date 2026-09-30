"""Audited daily workflows. Notes/templates are versioned through append-only writes."""
from django.db import models
from .models import Record, PatientRecord

class WorkTask(PatientRecord):
    patient = models.ForeignKey('demographics.Patient',null=True,blank=True,on_delete=models.PROTECT)
    facility = models.ForeignKey('accounts.Facility',null=True,on_delete=models.PROTECT)
    source_kind = models.CharField(max_length=30,blank=True)
    source_pk = models.PositiveBigIntegerField(null=True,blank=True)
    audience = models.CharField(max_length=20)
    title = models.CharField(max_length=160)
    instruction = models.TextField(blank=True)
    owner = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT, related_name='assigned_care_tasks')
    due_at = models.DateTimeField()
    status = models.CharField(max_length=16,default='open',choices=[('open','Open'),('in_progress','In progress'),('completed','Completed'),('cancelled','Cancelled')])
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True,blank=True)
    revision = models.PositiveIntegerField(default=1)
    encounter = models.ForeignKey('encounters.Encounter',null=True,blank=True,on_delete=models.PROTECT)
    class Meta:
        indexes=[models.Index(fields=['audience','status','due_at'])]

class NoteTemplate(Record):
    facility = models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    version = models.PositiveIntegerField()
    body = models.TextField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','name','version'],name='unique_note_template_version')]
    def __str__(self): return f'{self.name} · v{self.version}'

class ConsultationNote(PatientRecord):
    encounter = models.ForeignKey('encounters.Encounter',on_delete=models.PROTECT)
    body = models.TextField()
    template = models.ForeignKey(NoteTemplate,null=True,blank=True,on_delete=models.PROTECT)
    template_snapshot = models.TextField(blank=True)
    copied_from = models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    amends = models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT,related_name='+')

class PatientDocument(PatientRecord):
    title = models.CharField(max_length=160)
    file = models.FileField(upload_to='patient_documents/%Y/%m/')
    encounter = models.ForeignKey('encounters.Encounter',null=True,blank=True,on_delete=models.PROTECT)
