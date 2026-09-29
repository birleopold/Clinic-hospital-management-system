from decimal import Decimal
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Dispense, Prescription, PrescriptionItem


class PrescriptionItemSerializer(FacilityScopedSerializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), default=Decimal('1'))

    class Meta:
        model = PrescriptionItem
        fields = '__all__'
        read_only_fields = ('dispensed_quantity',)


class PrescriptionSerializer(FacilityScopedSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = '__all__'


class DispenseSerializer(FacilityScopedSerializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), default=Decimal('1'))

    class Meta:
        model = Dispense
        fields = '__all__'
