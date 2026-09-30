"""Audited staffing records. Clock events and patient workload are distinct."""
from django.db import models
from django.db.models import Q, F
from .models import Record


class StaffCredential(Record):
    staff = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    specialty = models.CharField(max_length=120, blank=True)
    credential = models.CharField(max_length=120)
    reference = models.CharField(max_length=120)
    expires_on = models.DateField()
    verified_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)


class DutyShift(Record):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    department = models.ForeignKey('accounts.Department', on_delete=models.PROTECT)
    staff = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='duty_shifts')
    supervisor = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    backup = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+', null=True, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    on_call = models.BooleanField(default=False)
    capacity = models.PositiveSmallIntegerField(default=10)
    status = models.CharField(max_length=12, default='draft', choices=[('draft','Draft'),('published','Published'),('cancelled','Cancelled')])
    availability = models.CharField(max_length=12, default='unavailable', choices=[('accepting','Accepting patients'),('unavailable','Unavailable')])
    reason = models.CharField(max_length=250, blank=True)
    revision = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')),name='duty_positive_interval'),models.CheckConstraint(condition=Q(capacity__gt=0),name='duty_positive_capacity')]
        indexes = [models.Index(fields=['facility','status','starts_at'],name='duty_facility_start_idx')]
    def __str__(self):
        return f'{self.staff} · {self.starts_at:%Y-%m-%d %H:%M} · {self.department}'


class Attendance(Record):
    shift = models.OneToOneField(DutyShift, on_delete=models.PROTECT, related_name='attendance')
    staff = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True)
    reviewed_by = models.ForeignKey('accounts.User', null=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['staff'],condition=Q(clock_out__isnull=True),name='one_open_staff_attendance'),models.CheckConstraint(condition=Q(clock_out__isnull=True)|Q(clock_out__gte=F('clock_in')),name='attendance_positive_interval')]


class AttendanceBreak(Record):
    attendance = models.ForeignKey(Attendance, on_delete=models.PROTECT, related_name='breaks')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['attendance'],condition=Q(ended_at__isnull=True),name='one_open_attendance_break'),models.CheckConstraint(condition=Q(ended_at__isnull=True)|Q(ended_at__gte=F('started_at')),name='break_positive_interval')]


class AttendanceCorrection(Record):
    attendance = models.ForeignKey(Attendance, on_delete=models.PROTECT, related_name='corrections')
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField()
    break_minutes = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=12, default='requested', choices=[('requested','Requested'),('approved','Approved'),('rejected','Rejected')])
    reviewed_by = models.ForeignKey('accounts.User',null=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(clock_out__gt=F('clock_in')),name='correction_positive_interval'),models.UniqueConstraint(fields=['attendance'],condition=Q(status='requested'),name='one_pending_attendance_correction')]


class StaffLeave(Record):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    staff = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=12,default='requested',choices=[('requested','Requested'),('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled')])
    reviewed_by = models.ForeignKey('accounts.User',null=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')),name='leave_positive_interval')]


class ShiftCover(Record):
    shift = models.ForeignKey(DutyShift,on_delete=models.PROTECT,related_name='cover_requests')
    original_staff = models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    replacement = models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    reason = models.CharField(max_length=250)
    accepted_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=12,default='requested',choices=[('requested','Requested'),('approved','Approved'),('rejected','Rejected')])
    reviewed_by = models.ForeignKey('accounts.User',null=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['shift'],condition=Q(status='requested'),name='one_pending_shift_cover')]


class ShiftHandover(Record):
    shift = models.ForeignKey(DutyShift,on_delete=models.PROTECT,related_name='handovers')
    incoming = models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    summary = models.TextField(help_text='Operational summary only. Keep clinical/HR details in their restricted source records.')
    due_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True)
    acknowledgment = models.CharField(max_length=250,blank=True)


class DutyAssignment(Record):
    encounter = models.ForeignKey('encounters.Encounter',on_delete=models.PROTECT,related_name='duty_assignments')
    shift = models.ForeignKey(DutyShift,on_delete=models.PROTECT)
    previous_clinician = models.ForeignKey('accounts.User',null=True,on_delete=models.PROTECT,related_name='+')
    reason = models.CharField(max_length=250)
