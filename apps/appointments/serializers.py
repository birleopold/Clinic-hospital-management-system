from rest_framework import serializers
from .models import Appointment, QueueTicket, DoctorWeeklyAvailability, DoctorTimeOff

class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = '__all__'


class QueueTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = QueueTicket
        fields = '__all__'


class DoctorWeeklyAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorWeeklyAvailability
        fields = '__all__'


class DoctorTimeOffSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorTimeOff
        fields = '__all__'
