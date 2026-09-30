from django.conf import settings
from django.db import models

class Appointment(models.Model):
    room = models.ForeignKey("operations.ServiceRoom", null=True, blank=True, on_delete=models.PROTECT)
    appointment_type = models.CharField(max_length=100, blank=True)
    def save(self, *args, **kwargs):
        from datetime import timedelta
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from apps.accounts.models import User
        with transaction.atomic():
            from apps.demographics.models import Patient
            patient = Patient.objects.select_for_update().get(pk=self.patient_id)
            if patient.merged_into_id:
                raise ValidationError('Select the canonical patient identity.')
            User.objects.select_for_update().get(pk=self.clinician_id)
            if not 1 <= self.duration_minutes <= 1440:
                raise ValidationError('Appointment duration must be between 1 and 1440 minutes.')
            previous = type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            transitions = {'scheduled':('confirmed','in_progress','cancelled','no_show'), 'confirmed':('in_progress','cancelled','no_show'), 'in_progress':('completed','cancelled')}
            if previous and previous.status != self.status and self.status not in transitions.get(previous.status, ()):
                raise ValidationError('Invalid appointment status transition.')
            if self.status not in ('cancelled','no_show'):
                end = self.scheduled_for + timedelta(minutes=self.duration_minutes)
                candidates = type(self).objects.filter(clinician_id=self.clinician_id, scheduled_for__lt=end, scheduled_for__gt=self.scheduled_for-timedelta(days=1)).exclude(status__in=['cancelled','no_show']).exclude(pk=self.pk)
                if any(a.scheduled_for + timedelta(minutes=a.duration_minutes) > self.scheduled_for for a in candidates):
                    raise ValidationError('This clinician already has an overlapping appointment.')
                if self.room_id:
                    from apps.operations.models import ServiceRoom
                    room=ServiceRoom.objects.select_for_update().get(pk=self.room_id)
                    if room.facility_id!=self.patient.facility_id:
                        raise ValidationError('Room must belong to the patient facility.')
                    room_bookings=type(self).objects.filter(room_id=self.room_id,scheduled_for__lt=end,scheduled_for__gt=self.scheduled_for-timedelta(days=1)).exclude(status__in=['cancelled','no_show']).exclude(pk=self.pk)
                    if any(a.scheduled_for+timedelta(minutes=a.duration_minutes)>self.scheduled_for for a in room_bookings):
                        raise ValidationError('This room already has an overlapping appointment.')
                from apps.operations.models import TheatreCase
                from django.db.models import Q
                theatre_resources = Q(surgeon_id=self.clinician_id) | Q(patient_id=self.patient_id)
                if self.room_id:
                    theatre_resources |= Q(room_id=self.room_id)
                if TheatreCase.objects.exclude(status__in=['cancelled','completed']).filter(theatre_resources, starts_at__lt=end, ends_at__gt=self.scheduled_for).exists():
                    raise ValidationError('The clinician or room has an overlapping theatre case.')
                from apps.operations.models import StaffLeave
                if StaffLeave.objects.filter(staff_id=self.clinician_id,status='approved',starts_at__lt=end,ends_at__gt=self.scheduled_for).exists():
                    raise ValidationError('Clinician has approved leave during this appointment.')
                if DoctorTimeOff.objects.filter(clinician_id=self.clinician_id,start__lt=end,end__gt=self.scheduled_for).exists():
                    raise ValidationError('Clinician is unavailable during this appointment.')
            return super().save(*args, **kwargs)

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
    def save(self, *args, **kwargs):
        from django.db import transaction
        from django.utils import timezone
        from django.core.exceptions import ValidationError
        with transaction.atomic():
            previous = type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            transitions = {'waiting':('in_service','cancelled'),'in_service':('done','cancelled')}
            if previous and previous.status != self.status and self.status not in transitions.get(previous.status, ()):
                raise ValidationError('Invalid queue transition.')
            if previous and previous.status == self.status:
                self.started_at, self.finished_at = previous.started_at, previous.finished_at
            elif self.status == 'in_service':
                self.started_at = timezone.now()
            elif self.status in ('done','cancelled'):
                self.finished_at = timezone.now()
            return super().save(*args, **kwargs)

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
