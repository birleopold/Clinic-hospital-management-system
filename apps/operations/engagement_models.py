import uuid
from django.db import models
from simple_history.models import HistoricalRecords
from .models import Record, PatientRecord


class PortalRecipient(Record):
    grant=models.OneToOneField('operations.PortalGrant',on_delete=models.PROTECT,related_name='verified_recipient')
    recipient_name=models.CharField(max_length=160)
    relationship=models.CharField(max_length=12,choices=[('patient','Patient'),('guardian','Authorized guardian')])
    verification_reference=models.CharField(max_length=250)
    authority_reference=models.CharField(max_length=250,blank=True)
    allow_appointment_requests=models.BooleanField(default=False)
    scopes=models.JSONField(default=list, blank=True, help_text='An empty list preserves historical summary access. New links use explicit scopes.')


class AppointmentRequest(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True)
    grant=models.ForeignKey('operations.PortalGrant',on_delete=models.PROTECT)
    patient=models.ForeignKey('demographics.Patient',on_delete=models.PROTECT)
    kind=models.CharField(max_length=12,default='new',choices=[('new','New booking'),('reschedule','Reschedule'),('cancel','Cancel booking')])
    target_appointment=models.ForeignKey('appointments.Appointment',null=True,blank=True,on_delete=models.PROTECT,related_name='change_requests')
    target_scheduled_for=models.DateTimeField(null=True,blank=True)
    preferred_date=models.DateField()
    reason=models.CharField(max_length=250)
    created_at=models.DateTimeField(auto_now_add=True)
    status=models.CharField(max_length=12,default='requested',choices=[('requested','Requested'),('booked','Booked'),('declined','Declined')])
    appointment=models.OneToOneField('appointments.Appointment',null=True,blank=True,on_delete=models.PROTECT)
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT)
    reviewed_at=models.DateTimeField(null=True,blank=True)
    response_note=models.CharField(max_length=250,blank=True)
    history=HistoricalRecords()


class PatientRecall(PatientRecord):
    owner=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    purpose=models.CharField(max_length=160)
    due_on=models.DateField()
    repeat_days=models.PositiveSmallIntegerField(default=0,help_text='0 means one follow-up. Repetition schedules from the completed review date, not a guessed clinical interval.')
    status=models.CharField(max_length=12,default='open',choices=[('open','Open'),('completed','Completed'),('cancelled','Cancelled')])
    outcome=models.CharField(max_length=250,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    next_recall=models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='previous_recall')
