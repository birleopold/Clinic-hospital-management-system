from django.conf import settings
from django.db import models

class Appointment(models.Model):
    SCHEDULED = 'scheduled'
    CONFIRMED = 'confirmed'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    NO_SHOW = 'no_show'

    STATUS_CHOICES = [
        (SCHEDULED, 'Scheduled'),
        (CONFIRMED, 'Confirmed'),
        (IN_PROGRESS, 'In Progress'),
        (COMPLETED, 'Completed'),
        (CANCELLED, 'Cancelled'),
        (NO_SHOW, 'No Show'),
    ]

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    scheduled_for = models.DateTimeField()
    duration_minutes = models.IntegerField(default=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SCHEDULED)
    reason_for_visit = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.patient} @ {self.scheduled_for}"


class QueueTicket(models.Model):
    TRIAGE = 'triage'
    CONSULT = 'consult'
    LAB = 'lab'
    PHARMACY = 'pharmacy'
    CASHIER = 'cashier'
    SERVICE_CHOICES = [
        (TRIAGE, 'Triage'),
        (CONSULT, 'Consult'),
        (LAB, 'Lab'),
        (PHARMACY, 'Pharmacy'),
        (CASHIER, 'Cashier'),
    ]

    WAITING = 'waiting'
    IN_SERVICE = 'in_service'
    DONE = 'done'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (WAITING, 'Waiting'),
        (IN_SERVICE, 'In Service'),
        (DONE, 'Done'),
        (CANCELLED, 'Cancelled'),
    ]

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    service = models.CharField(max_length=16, choices=SERVICE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    appointment = models.ForeignKey('appointments.Appointment', on_delete=models.SET_NULL, null=True, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.patient} → {self.service} [{self.status}]"


class DoctorWeeklyAvailability(models.Model):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6
    DOW_CHOICES = [
        (MONDAY, 'Monday'),
        (TUESDAY, 'Tuesday'),
        (WEDNESDAY, 'Wednesday'),
        (THURSDAY, 'Thursday'),
        (FRIDAY, 'Friday'),
        (SATURDAY, 'Saturday'),
        (SUNDAY, 'Sunday'),
    ]

    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day_of_week = models.IntegerField(choices=DOW_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    location = models.CharField(max_length=128, blank=True)
    default_duration_minutes = models.IntegerField(default=30)
    buffer_minutes = models.IntegerField(default=0)

    class Meta:
        ordering = ['clinician', 'day_of_week', 'start_time']

    def __str__(self):
        return f"{self.clinician} {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"


class DoctorTimeOff(models.Model):
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['clinician', 'start']

    def __str__(self):
        return f"{self.clinician} off {self.start} → {self.end}"
