from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Appointment, QueueTicket, DoctorWeeklyAvailability, DoctorTimeOff

class AppointmentSerializer(FacilityScopedSerializer):
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=30)

    class Meta:
        model = Appointment
        fields = '__all__'


class QueueTicketSerializer(FacilityScopedSerializer):
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
