"""Account access changes must not strand active care or operational work."""
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone


def require_work_reassignment(user):
    from apps.billing.models import CashSession
    from apps.encounters.models import Encounter
    from apps.operations.models import Attendance, DutyShift, WorkTask, DiagnosticWorkItem

    checks=(
        ('open cash sessions', CashSession.objects.filter(opened_by=user,close_time__isnull=True)),
        ('open consultations', Encounter.objects.filter(clinician=user,status='open')),
        ('open attendance', Attendance.objects.filter(staff=user,clock_out__isnull=True)),
        ('assigned tasks', WorkTask.objects.filter(owner=user,status__in=['open','in_progress'])),
        ('published duties, supervision or backup coverage', DutyShift.objects.filter(
            Q(staff=user)|Q(supervisor=user)|Q(backup=user),status='published',ends_at__gt=timezone.now())),
        ('assigned diagnostic work', DiagnosticWorkItem.objects.filter(operator=user,completed_at__isnull=True).exclude(order__status='cancelled')),
    )
    outstanding=[label for label,queryset in checks if queryset.exists()]
    if outstanding:
        raise ValidationError('Reassign or close '+', '.join(outstanding)+' before changing this staff member’s role or disabling access.')
