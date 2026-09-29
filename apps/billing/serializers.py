from rest_framework import serializers
from .models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment

class PriceListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceListItem
        fields = '__all__'

class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ('id','code','description','quantity','unit_price','line_total','source_ref')
        read_only_fields = ('line_total',)

class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = ('id','patient','total_amount','paid_amount','status','created_at','lines')
        read_only_fields = ('total_amount','paid_amount','status','created_at','lines')

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'
