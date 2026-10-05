from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from common.service_policy import enabled_queue_services
from .models import Appointment, QueueTicket, DoctorWeeklyAvailability, DoctorTimeOff
from .queue_policy import can_work_queue

class AppointmentSerializer(FacilityScopedSerializer):
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=30)

    class Meta:
        model = Appointment
        fields = '__all__'


class QueueTicketSerializer(FacilityScopedSerializer):
    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.is_authenticated:
            allowed = enabled_queue_services(user)
            fields['service'].choices = [
                (value, label) for value, label in QueueTicket.SERVICE_CHOICES
                if value in allowed
            ]
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = getattr(self.context.get('request'), 'user', None)
        service = attrs.get('service', getattr(self.instance, 'service', None))
        if not user or not user.is_authenticated or service not in enabled_queue_services(user):
            raise serializers.ValidationError({'service': 'This queue service is not enabled.'})
        if self.instance:
            for field in ('patient','service','appointment','status','assigned_to'):
                if field in attrs and attrs[field] != getattr(self.instance,field):
                    raise serializers.ValidationError({field:'Use the queue workflow actions; an existing ticket keeps its patient, service and appointment.'})
            if not can_work_queue(user,self.instance.service) and user.role!='reception':
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('Only the receiving department or reception may update queue notes.')
        elif attrs.get('status',QueueTicket.WAITING)!=QueueTicket.WAITING or attrs.get('assigned_to') is not None:
            raise serializers.ValidationError('New tickets must be waiting and unassigned. The receiving department starts the ticket.')
        return attrs

    class Meta:
        model = QueueTicket
        fields = '__all__'
        read_only_fields = ('started_at','finished_at','created_at')


class DoctorWeeklyAvailabilitySerializer(FacilityScopedSerializer):
    default_duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=30)
    buffer_minutes = serializers.IntegerField(min_value=0, max_value=1440, default=0)

    class Meta:
        model = DoctorWeeklyAvailability
        fields = '__all__'


class DoctorTimeOffSerializer(FacilityScopedSerializer):
    class Meta:
        model = DoctorTimeOff
        fields = '__all__'
