from decimal import Decimal
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Order, OrderResult


class OrderResultSerializer(FacilityScopedSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.attachment:
            data["attachment"] = f"/suite/results/{instance.pk}/download/"
        return data

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance and hasattr(self.instance, "worksheet"):
            raise serializers.ValidationError("Structured worksheets are immutable. Withdraw a draft or add an amended worksheet.")
        prior = attrs.get("supersedes")
        order = attrs.get("order", self.instance.order if self.instance else None)
        if prior and (
            prior.order_id != getattr(order, "pk", None) or not prior.approved_at
        ):
            raise serializers.ValidationError(
                "Amendments must reference a released result for this order."
            )
        if self.instance and self.instance.approved_at:
            raise serializers.ValidationError(
                "Released results are immutable. Add an amended result."
            )
        from .models import OrderResult
        from apps.operations.advanced_validation import validate_new_record
        from django.core.exceptions import ValidationError
        import copy

        candidate = copy.copy(self.instance) if self.instance else OrderResult()
        for key, value in attrs.items():
            setattr(candidate, key, value)
        try:
            validate_new_record(
                candidate, getattr(self.context.get("request"), "user", None)
            )
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        if candidate.catalog_analyte_id:
            for field in ("analyte", "units", "reference_range"):
                attrs[field] = getattr(candidate, field)
        return attrs

    class Meta:
        model = OrderResult
        fields = "__all__"
        read_only_fields = (
            "recorded_at",
            "recorded_by",
            "approved_at",
            "approved_by",
            "acknowledged_at",
            "acknowledged_by",
        )


class OrderSerializer(FacilityScopedSerializer):
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), default=Decimal("1")
    )
    results = OrderResultSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = "__all__"
        read_only_fields = ("status", "created_at")
