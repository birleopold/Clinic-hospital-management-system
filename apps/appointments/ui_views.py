from collections import defaultdict
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.utils import timezone
from datetime import datetime, time as dtime, timedelta
from django.contrib.auth import get_user_model
import calendar

from .models import QueueTicket, Appointment, DoctorWeeklyAvailability, DoctorTimeOff
from common.facility_scope import filter_by_facility, filter_by_patient_facility


@login_required
def home_view(request):
    from datetime import datetime
    from django.utils.timezone import make_aware
    from decimal import Decimal
    from apps.billing.models import Payment, InvoiceLine
    from apps.demographics.models import Patient

    user = request.user

    # Today range
    now = datetime.now()
    start = make_aware(datetime(now.year, now.month, now.day, 0, 0, 0))
    end = make_aware(datetime(now.year, now.month, now.day, 23, 59, 59))

    # KPIs
    from django.db.models import Sum
    revenue_total = (
        filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__')
        .filter(paid_at__range=(start, end))
        .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    )
    new_patients = filter_by_facility(Patient.objects.all(), user).filter(created_at__range=(start, end)).count()

    # Queue snapshot
    qs = (
        filter_by_patient_facility(QueueTicket.objects.all(), user)
        .values('service', 'status')
        .annotate(count=Count('id'))
    )
    services = [s for s, _ in QueueTicket.SERVICE_CHOICES]
    statuses = [s for s, _ in QueueTicket.STATUS_CHOICES]
    data = {svc: {st: 0 for st in statuses} for svc in services}
    for row in qs:
        data[row['service']][row['status']] = row['count']

    # Service mix today (top 5)
    mix = (
        filter_by_patient_facility(InvoiceLine.objects.all(), user, prefix='invoice__patient__')
        .filter(created_at__range=(start, end))
        .values('code')
        .annotate(total_amount=Sum('line_total'), total_qty=Sum('quantity'))
        .order_by('-total_amount')[:5]
    )
    mix_rows = [
        {
            'code': r['code'],
            'total_amount': r['total_amount'] or Decimal('0.00'),
            'total_qty': r['total_qty'] or Decimal('0.00'),
        }
        for r in mix
    ]

    context = {
        'revenue_total': revenue_total,
        'new_patients': new_patients,
        'services': QueueTicket.SERVICE_CHOICES,
        'statuses': QueueTicket.STATUS_CHOICES,
        'data': data,
        'service_mix': mix_rows,
    }
    return render(request, 'dashboard/home.html', context)

@login_required
def queue_summary_view(request):
    user = request.user
    # Aggregate counts by service and status
    qs = (
        filter_by_patient_facility(QueueTicket.objects.all(), user)
        .values('service', 'status')
        .annotate(count=Count('id'))
    )
    services = [s for s, _ in QueueTicket.SERVICE_CHOICES]
    statuses = [s for s, _ in QueueTicket.STATUS_CHOICES]
    data = {svc: {st: 0 for st in statuses} for svc in services}
    for row in qs:
        data[row['service']][row['status']] = row['count']
    context = {
        'services': QueueTicket.SERVICE_CHOICES,
        'statuses': QueueTicket.STATUS_CHOICES,
        'data': data,
    }
    return render(request, 'queues/summary.html', context)


@login_required
def queue_service_view(request, service: str):
    user = request.user
    base = filter_by_patient_facility(QueueTicket.objects.all(), user)
    waiting = base.filter(service=service, status=QueueTicket.WAITING).order_by('created_at')
    in_service = base.filter(service=service, status=QueueTicket.IN_SERVICE).order_by('started_at')
    context = {
        'service': service,
        'service_label': dict(QueueTicket.SERVICE_CHOICES).get(service, service.title()),
        'waiting': waiting,
        'in_service': in_service,
    }
    return render(request, 'queues/service.html', context)


@login_required
def calendar_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','reception','clinician')):
        return HttpResponseForbidden('Not allowed')
    appt_qs = filter_by_patient_facility(Appointment.objects.all(), user)
    User = get_user_model()
    clinicians = list(User.objects.filter(role='clinician').order_by('first_name','last_name','username'))
    selected_clinician = request.GET.get('clinician')
    if selected_clinician:
        try:
            selected_clinician = int(selected_clinician)
        except Exception:
            selected_clinician = None
    if not selected_clinician:
        if user.role == 'clinician':
            selected_clinician = user.id
        elif clinicians:
            selected_clinician = clinicians[0].id
    qdate_str = request.GET.get('date')
    try:
        qdate = datetime.strptime(qdate_str, '%Y-%m-%d').date() if qdate_str else timezone.localdate()
    except Exception:
        qdate = timezone.localdate()
    # Default duration from availability for the selected day
    try:
        dur_q = request.GET.get('duration')
        duration = int(dur_q) if dur_q is not None else None
    except Exception:
        duration = None
    if duration is None:
        dow = (qdate.weekday())
        av = DoctorWeeklyAvailability.objects.filter(clinician_id=selected_clinician, day_of_week=dow, is_active=True).order_by('start_time').first()
        duration = av.default_duration_minutes if av else 30
    mode = (request.GET.get('mode') or 'day').lower()

    # Compute data by mode
    prev_date = (qdate - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (qdate + timedelta(days=1)).strftime('%Y-%m-%d')
    day_appointments = []
    week_days = []
    appts_by_day = {}
    month_weeks = []

    if mode == 'week':
        week_start = qdate - timedelta(days=qdate.weekday())  # Monday
        week_end = week_start + timedelta(days=6)
        start_dt = timezone.make_aware(datetime.combine(week_start, dtime.min))
        end_dt = timezone.make_aware(datetime.combine(week_end, dtime.max))
        appts = appt_qs.filter(
            clinician_id=selected_clinician,
            scheduled_for__gte=start_dt,
            scheduled_for__lte=end_dt,
        ).order_by('scheduled_for')
        cur_tz = timezone.get_current_timezone()
        appts_by_day = defaultdict(list)
        for ap in appts:
            d = ap.scheduled_for.astimezone(cur_tz).date().strftime('%Y-%m-%d')
            appts_by_day[d].append(ap)
        week_days = [
            {
                'date': (week_start + timedelta(days=i)).strftime('%Y-%m-%d'),
                'label': (week_start + timedelta(days=i)).strftime('%a %d %b'),
            }
            for i in range(7)
        ]
        week_columns = [
            {
                'date': d['date'],
                'label': d['label'],
                'appts': appts_by_day.get(d['date'], []),
            }
            for d in week_days
        ]
        prev_date = (week_start - timedelta(days=7)).strftime('%Y-%m-%d')
        next_date = (week_start + timedelta(days=7)).strftime('%Y-%m-%d')
    elif mode == 'month':
        first = qdate.replace(day=1)
        _, num_days = calendar.monthrange(first.year, first.month)
        last = first.replace(day=num_days)
        month_start = first - timedelta(days=first.weekday())
        month_end = last + timedelta(days=(6 - last.weekday()))
        start_dt = timezone.make_aware(datetime.combine(month_start, dtime.min))
        end_dt = timezone.make_aware(datetime.combine(month_end, dtime.max))
        counts = (
            appt_qs.filter(
                clinician_id=selected_clinician,
                scheduled_for__gte=start_dt,
                scheduled_for__lte=end_dt,
            ).annotate(day=TruncDate('scheduled_for')).values('day').annotate(c=Count('id'))
        )
        count_map = { row['day'].strftime('%Y-%m-%d'): row['c'] for row in counts }
        cur = month_start
        while cur <= month_end:
            week = []
            for i in range(7):
                d = cur + timedelta(days=i)
                key = d.strftime('%Y-%m-%d')
                week.append({
                    'date': key,
                    'day': d.day,
                    'in_month': d.month == first.month,
                    'count': count_map.get(key, 0),
                })
            month_weeks.append(week)
            cur += timedelta(days=7)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = (last + timedelta(days=1)).replace(day=1)
        prev_date = prev_month.strftime('%Y-%m-%d')
        next_date = next_month.strftime('%Y-%m-%d')
    else:
        # Day mode
        start_dt = timezone.make_aware(datetime.combine(qdate, dtime.min))
        end_dt = timezone.make_aware(datetime.combine(qdate, dtime.max))
        day_appointments = appt_qs.filter(
            clinician_id=selected_clinician,
            scheduled_for__gte=start_dt,
            scheduled_for__lte=end_dt,
        ).order_by('scheduled_for')

    context = {
        'clinicians': clinicians,
        'selected_clinician': selected_clinician,
        'date': qdate.strftime('%Y-%m-%d'),
        'duration': duration,
        'appointments': day_appointments,
        'mode': mode,
        'week_days': week_days,
        'appts_by_day': appts_by_day,
        'week_columns': locals().get('week_columns', []),
        'month_weeks': month_weeks,
        'prev_date': prev_date,
        'next_date': next_date,
    }
    return render(request, 'appointments/calendar.html', context)


@login_required
def appointment_slots_fragment(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','reception','clinician')):
        return HttpResponseForbidden('Not allowed')
    appt_qs = filter_by_patient_facility(Appointment.objects.all(), user)
    try:
        clinician_id = int(request.GET.get('clinician'))
    except Exception:
        clinician_id = None
    date_str = request.GET.get('date')
    try:
        qdate = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.localdate()
    except Exception:
        qdate = timezone.localdate()
    # Effective duration defaults to clinician/day availability
    try:
        duration = int(request.GET.get('duration'))
    except Exception:
        duration = None
    dow = qdate.weekday()
    avails = DoctorWeeklyAvailability.objects.filter(
        clinician_id=clinician_id, day_of_week=dow, is_active=True
    ).order_by('start_time')
    default_av = avails.first()
    if duration is None:
        duration = default_av.default_duration_minutes if default_av else 30
    try:
        slot_minutes = int(request.GET.get('slot') or duration)
    except Exception:
        slot_minutes = duration

    # Buffer minutes from availability; use the first active as baseline
    buffer_minutes = default_av.buffer_minutes if default_av else 0
    start_dt = timezone.make_aware(datetime.combine(qdate, dtime.min))
    end_dt = timezone.make_aware(datetime.combine(qdate, dtime.max))
    active_statuses = [
        Appointment.SCHEDULED,
        Appointment.CONFIRMED,
        Appointment.IN_PROGRESS,
        Appointment.COMPLETED,
    ]
    appts = list(
        appt_qs.filter(
            clinician_id=clinician_id,
            scheduled_for__gte=start_dt,
            scheduled_for__lte=end_dt,
            status__in=active_statuses,
        )
    )
    offs = list(
        DoctorTimeOff.objects.filter(
            clinician_id=clinician_id,
            end__gte=start_dt,
            start__lte=end_dt,
        )
    )

    def overlaps(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    slots = []
    for av in avails:
        w_start = timezone.make_aware(datetime.combine(qdate, av.start_time))
        w_end = timezone.make_aware(datetime.combine(qdate, av.end_time))
        cur = w_start
        last_start = w_end - timedelta(minutes=duration)
        while cur <= last_start:
            s_end = cur + timedelta(minutes=duration)
            # time off
            if any(overlaps(cur, s_end, off.start, off.end) for off in offs):
                cur += timedelta(minutes=slot_minutes)
                continue
            # appointment conflicts (respect buffer after existing appt)
            conflict = False
            for ap in appts:
                ap_end = ap.scheduled_for + timedelta(minutes=ap.duration_minutes + buffer_minutes)
                # Also ensure our proposed slot leaves buffer after it ends before the next starts
                if overlaps(cur, s_end + timedelta(minutes=buffer_minutes), ap.scheduled_for, ap_end):
                    conflict = True
                    break
            if not conflict:
                slots.append(cur)
            cur += timedelta(minutes=slot_minutes)

    context = {
        'clinician_id': clinician_id,
        'date': qdate.strftime('%Y-%m-%d'),
        'duration': duration,
        'slots': slots,
        'appt': request.GET.get('appt') or '',
    }
    if (request.GET.get('mode') or '').lower() == 'reschedule':
        return render(request, 'appointments/_slots_reschedule.html', context)
    return render(request, 'appointments/_slots.html', context)
