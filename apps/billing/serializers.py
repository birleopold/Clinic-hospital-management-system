from decimal import Decimal
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment

class PriceListItemSerializer(FacilityScopedSerializer):
    class Meta:
        model = PriceListItem
        fields = '__all__'

class InvoiceLineSerializer(FacilityScopedSerializer):
    class Meta:
        model = InvoiceLine
        fields = ('id','code','description','quantity','unit_price','line_total','source_ref')
        read_only_fields = ('line_total',)

class InvoiceSerializer(FacilityScopedSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = ('id','patient','total_amount','paid_amount','status','created_at','lines')
        read_only_fields = ('total_amount','paid_amount','status','created_at','lines')

class PaymentSerializer(FacilityScopedSerializer):
    idempotency_key = serializers.UUIDField(write_only=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('cash_session', 'paid_at')
