from datetime import datetime, timedelta, time as dtime
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import RolePermission
from common.service_policy import enabled_queue_services
from common.facility_scope import filter_by_facility, filter_by_patient_facility
from .models import Appointment, QueueTicket, DoctorWeeklyAvailability, DoctorTimeOff
from .serializers import (
    AppointmentSerializer,
    QueueTicketSerializer,
    DoctorWeeklyAvailabilitySerializer,
    DoctorTimeOffSerializer,
)


class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.all().order_by('-scheduled_for')
    serializer_class = AppointmentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['reason_for_visit','notes','patient__first_name','patient__last_name']
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin', 'reception', 'clinician'],
        'POST': ['admin','reception','clinician'],
        'PUT': ['admin','reception'],
        'PATCH': ['admin','reception','clinician'],
        'DELETE': ['admin'],
        'confirm': ['admin','reception','clinician'],
        'cancel': ['admin','reception','clinician'],
        'reschedule': ['admin','reception','clinician'],
        'no_show': ['admin','reception','clinician'],
        'available_slots': ['admin','reception','clinician'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(super().get_queryset(), self.request.user)

    @action(detail=False, methods=['get'])
    def available_slots(self, request):
        try:
            clinician_id = int(request.query_params.get('clinician'))
        except Exception:
            return Response({'detail': 'clinician is required'}, status=400)
        date_str = request.query_params.get('date')
        try:
            qdate = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.localdate()
        except Exception:
            return Response({'detail': 'invalid date'}, status=400)
        try:
            duration = int(request.query_params.get('duration', '30'))
            slot_minutes = int(request.query_params.get('slot', str(duration)))
            if not 1 <= duration <= 1440 or not 1 <= slot_minutes <= 1440:
                raise ValueError
        except (TypeError, ValueError):
            return Response({'detail': 'duration and slot must be integers from 1 to 1440 minutes'}, status=400)

        from django.contrib.auth import get_user_model
        clinicians = filter_by_facility(
            get_user_model().objects.filter(is_active=True, role='clinician'),
            request.user, field='staff_profile__facility_id',
        )
        if not clinicians.filter(pk=clinician_id).exists():
            return Response({'detail': 'Clinician not available in this facility.'}, status=404)

        dow = qdate.weekday()  # Monday=0
        avails = DoctorWeeklyAvailability.objects.filter(
            clinician_id=clinician_id, day_of_week=dow, is_active=True
        ).order_by('start_time')
        start_dt = timezone.make_aware(datetime.combine(qdate, dtime.min))
        end_dt = timezone.make_aware(datetime.combine(qdate, dtime.max))
        # Existing active appointments for the day
        active_statuses = [
            Appointment.SCHEDULED,
            Appointment.CONFIRMED,
            Appointment.IN_PROGRESS,
            Appointment.COMPLETED,
        ]
        appts = list(
            self.get_queryset().filter(
                clinician_id=clinician_id,
                scheduled_for__gte=start_dt,
                scheduled_for__lte=end_dt,
                status__in=active_statuses,
            )
        )
        # Time off overlapping the day
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
                # Check time off
                blocked = False
                for off in offs:
                    if overlaps(cur, s_end, off.start, off.end):
                        blocked = True
                        break
                if blocked:
                    cur += timedelta(minutes=slot_minutes)
                    continue
                # Check appointments
                conflict = False
                for ap in appts:
                    ap_end = ap.scheduled_for + timedelta(minutes=ap.duration_minutes)
                    if overlaps(cur, s_end, ap.scheduled_for, ap_end):
                        conflict = True
                        break
                if not conflict:
                    slots.append(cur)
                cur += timedelta(minutes=slot_minutes)

        return Response([
            {
                'start': s.isoformat(),
                'label': s.astimezone(timezone.get_current_timezone()).strftime('%H:%M'),
            }
            for s in slots
        ])

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        appt = self.get_object()
        appt.status = Appointment.CONFIRMED
        appt.save(update_fields=['status'])
        return Response(self.get_serializer(appt).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        appt = self.get_object()
        appt.status = Appointment.CANCELLED
        appt.save(update_fields=['status'])
        return Response(self.get_serializer(appt).data)

    @action(detail=True, methods=['post'])
    def no_show(self, request, pk=None):
        appt = self.get_object()
        appt.status = Appointment.NO_SHOW
        appt.save(update_fields=['status'])
        return Response(self.get_serializer(appt).data)

    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        appt = self.get_object()
        new_time = request.data.get('scheduled_for')
        try:
            new_dt = datetime.fromisoformat(new_time)
            if timezone.is_naive(new_dt):
                new_dt = timezone.make_aware(new_dt)
        except Exception:
            return Response({'detail': 'invalid scheduled_for'}, status=400)
        # Optional clinician or duration
        try:
            clinician_id = int(request.data.get('clinician', appt.clinician_id))
            duration = int(request.data.get('duration_minutes', appt.duration_minutes))
            if clinician_id < 1 or not 1 <= duration <= 1440:
                raise ValueError
        except (TypeError, ValueError):
            return Response({'detail': 'Invalid clinician or duration_minutes (1 to 1440)'}, status=400)

        from django.contrib.auth import get_user_model
        if not filter_by_facility(
            get_user_model().objects.filter(is_active=True, role='clinician'),
            request.user, field='staff_profile__facility_id',
        ).filter(pk=clinician_id).exists():
            return Response({'detail': 'Clinician not available in this facility.'}, status=400)

        # Basic conflict check using available_slots logic for that exact start
        req_date = new_dt.astimezone(timezone.get_current_timezone()).date()
        request._request.GET = request._request.GET.copy()
        # we will inline minimal checks here
        dow = req_date.weekday()
        avails = DoctorWeeklyAvailability.objects.filter(
            clinician_id=clinician_id, day_of_week=dow, is_active=True
        )
        within_avail = any(
            timezone.make_aware(datetime.combine(req_date, av.start_time)) <= new_dt <= (timezone.make_aware(datetime.combine(req_date, av.end_time)) - timedelta(minutes=duration))
            for av in avails
        )
        if not within_avail:
            return Response({'detail': 'outside availability'}, status=400)
        # time off
        if DoctorTimeOff.objects.filter(clinician_id=clinician_id, start__lt=new_dt + timedelta(minutes=duration), end__gt=new_dt).exists():
            return Response({'detail': 'on time off'}, status=400)
        # appointment conflicts excluding self
        active_statuses = [
            Appointment.SCHEDULED,
            Appointment.CONFIRMED,
            Appointment.IN_PROGRESS,
            Appointment.COMPLETED,
        ]
        for ap in Appointment.objects.filter(clinician_id=clinician_id, status__in=active_statuses).exclude(id=appt.id):
            ap_end = ap.scheduled_for + timedelta(minutes=ap.duration_minutes)
            if new_dt < ap_end and ap.scheduled_for < (new_dt + timedelta(minutes=duration)):
                return Response({'detail': 'conflict with another appointment'}, status=400)

        appt.scheduled_for = new_dt
        appt.clinician_id = clinician_id
        appt.duration_minutes = duration
        appt.status = Appointment.SCHEDULED
        appt.save(update_fields=['scheduled_for','clinician','duration_minutes','status'])
        return Response(self.get_serializer(appt).data)


class QueueTicketViewSet(viewsets.ModelViewSet):
    queryset = QueueTicket.objects.all()
    serializer_class = QueueTicketSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','reception'],  # enqueue via create
        'PUT': ['admin','reception','nurse','clinician','lab','pharmacy','cashier'],
        'PATCH': ['admin','reception','nurse','clinician','lab','pharmacy','cashier'],
        'DELETE': ['admin','reception'],
        'start': ['admin','nurse','clinician','lab','pharmacy','cashier'],
        'finish': ['admin','nurse','clinician','lab','pharmacy','cashier'],
        'cancel': ['admin','reception'],
    }

    def get_queryset(self):
        qs = filter_by_patient_facility(super().get_queryset(), self.request.user).filter(
            service__in=enabled_queue_services(self.request.user),
        )
        service = self.request.query_params.get('service')
        status_p = self.request.query_params.get('status')
        if service:
            qs = qs.filter(service=service)
        if status_p:
            qs = qs.filter(status=status_p)
        return qs.order_by('created_at')

    @action(detail=False, methods=['post'])
    def enqueue(self, request):
        # Alias for create, ensures status is waiting
        data = request.data.copy()
        data['status'] = QueueTicket.WAITING
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        ticket = self.get_object()
        # Enforce role matches service
        svc_role_map = {
            QueueTicket.TRIAGE: 'nurse',
            QueueTicket.CONSULT: 'clinician',
            QueueTicket.LAB: 'lab',
            QueueTicket.PHARMACY: 'pharmacy',
            QueueTicket.CASHIER: 'cashier',
        }
        expected_role = svc_role_map.get(ticket.service)
        if request.user.role not in ['admin', expected_role]:
            return Response({'detail': 'Not allowed for your role'}, status=status.HTTP_403_FORBIDDEN)
        ticket.status = QueueTicket.IN_SERVICE
        ticket.started_at = timezone.now()
        ticket.assigned_to = request.user
        ticket.save(update_fields=['status','started_at','assigned_to'])
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=['post'])
    def finish(self, request, pk=None):
        ticket = self.get_object()
        svc_role_map = {
            QueueTicket.TRIAGE: 'nurse',
            QueueTicket.CONSULT: 'clinician',
            QueueTicket.LAB: 'lab',
            QueueTicket.PHARMACY: 'pharmacy',
            QueueTicket.CASHIER: 'cashier',
        }
        expected_role = svc_role_map.get(ticket.service)
        if request.user.role not in ['admin', expected_role]:
            return Response({'detail': 'Not allowed for your role'}, status=status.HTTP_403_FORBIDDEN)
        ticket.status = QueueTicket.DONE
        ticket.finished_at = timezone.now()
        ticket.save(update_fields=['status','finished_at'])
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        ticket = self.get_object()
        # Reception or admin can cancel
        if request.user.role not in ['admin', 'reception']:
            return Response({'detail': 'Not allowed for your role'}, status=status.HTTP_403_FORBIDDEN)
        ticket.status = QueueTicket.CANCELLED
        ticket.finished_at = timezone.now()
        ticket.save(update_fields=['status','finished_at'])
        return Response(self.get_serializer(ticket).data)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        from django.db.models import Count
        qs = self.get_queryset()
        agg = qs.values('service','status').annotate(count=Count('id'))
        return Response(list(agg))


class DoctorWeeklyAvailabilityViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return filter_by_facility(
            super().get_queryset(), self.request.user,
            field='clinician__staff_profile__facility_id',
        )

    queryset = DoctorWeeklyAvailability.objects.all()
    serializer_class = DoctorWeeklyAvailabilitySerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin'],
        'PUT': ['admin'],
        'PATCH': ['admin'],
        'DELETE': ['admin'],
        'GET': ['admin','reception','clinician'],
    }


class DoctorTimeOffViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return filter_by_facility(
            super().get_queryset(), self.request.user,
            field='clinician__staff_profile__facility_id',
        )

    queryset = DoctorTimeOff.objects.all()
    serializer_class = DoctorTimeOffSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin'],
        'PUT': ['admin'],
        'PATCH': ['admin'],
        'DELETE': ['admin'],
        'GET': ['admin','reception','clinician'],
    }
