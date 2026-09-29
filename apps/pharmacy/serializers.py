from rest_framework import serializers
from .models import Dispense, Prescription, PrescriptionItem


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        fields = '__all__'


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = '__all__'


class DispenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispense
        fields = '__all__'
