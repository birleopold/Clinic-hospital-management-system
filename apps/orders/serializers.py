from rest_framework import serializers
from .models import Order, OrderResult


class OrderResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderResult
        fields = '__all__'
        read_only_fields = ('recorded_at',)


class OrderSerializer(serializers.ModelSerializer):
    results = OrderResultSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ('status', 'created_at')
