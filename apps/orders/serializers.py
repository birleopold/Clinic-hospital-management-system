from decimal import Decimal
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Order, OrderResult


class OrderResultSerializer(FacilityScopedSerializer):
    class Meta:
        model = OrderResult
        fields = '__all__'
        read_only_fields = ('recorded_at',)


class OrderSerializer(FacilityScopedSerializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), default=Decimal('1'))
    results = OrderResultSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ('status', 'created_at')
