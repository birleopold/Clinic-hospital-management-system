"""Response schemas for reporting endpoints (amounts are serialized as strings)."""
from rest_framework import serializers


class ReportPeriodSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class DailyRevenueSerializer(ReportPeriodSerializer):
    total_revenue = serializers.CharField()


class PatientVolumesSerializer(ReportPeriodSerializer):
    new_patients = serializers.IntegerField()


class ServiceMixRowSerializer(serializers.Serializer):
    code = serializers.CharField()
    total_amount = serializers.CharField()
    total_qty = serializers.CharField()


class ServiceMixSerializer(ReportPeriodSerializer):
    service_mix = ServiceMixRowSerializer(many=True)


class InvoiceRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    patient_id = serializers.IntegerField()
    patient = serializers.CharField()
    total_amount = serializers.CharField()
    paid_amount = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class RawInvoicesSerializer(ReportPeriodSerializer):
    count = serializers.IntegerField()
    rows = InvoiceRowSerializer(many=True)


class PaymentRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    invoice_id = serializers.IntegerField()
    patient_id = serializers.IntegerField()
    patient = serializers.CharField()
    amount = serializers.CharField()
    method = serializers.CharField()
    paid_at = serializers.DateTimeField()


class RawPaymentsSerializer(ReportPeriodSerializer):
    count = serializers.IntegerField()
    rows = PaymentRowSerializer(many=True)
