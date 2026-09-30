from django.db import models
from .models import Record


class PatientImportBatch(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    source=models.CharField(max_length=100)
    rows=models.JSONField(default=list)
    errors=models.JSONField(default=list)
    fingerprint=models.CharField(max_length=64)
    status=models.CharField(max_length=16,default='preview',choices=[('preview','Preview'),('committed','Committed'),('cancelled','Cancelled')])
    created_count=models.PositiveIntegerField(default=0)
    skipped_count=models.PositiveIntegerField(default=0)
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)


class PatientImportIdentity(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    source=models.CharField(max_length=100)
    external_id=models.CharField(max_length=100)
    patient=models.ForeignKey('demographics.Patient',on_delete=models.PROTECT)
    fingerprint=models.CharField(max_length=64)
    batch=models.ForeignKey(PatientImportBatch,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','source','external_id'],name='unique_patient_import_identity')]
