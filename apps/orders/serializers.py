from decimal import Decimal
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Order, OrderResult
from .permissions import filter_visible_results


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
        from common.service_policy import enabled
        candidate_order=attrs.get('order',self.instance.order if self.instance else None)
        if candidate_order and not enabled(self.context['request'].user,candidate_order.order_type if candidate_order.order_type!='procedure' else 'clinical'):
            raise serializers.ValidationError('This order service is disabled.')
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
    def validate(self,attrs):
        attrs=super().validate(attrs)
        from common.service_policy import enabled
        kind=attrs.get('order_type',self.instance.order_type if self.instance else '')
        service='clinical' if kind=='procedure' else kind
        if not enabled(self.context['request'].user,service):raise serializers.ValidationError('This order service is disabled.')
        if not enabled(self.context['request'].user,'billing'):
            if attrs.get('billable') or (self.instance and self.instance.billable):raise serializers.ValidationError('Enable billing before creating or modifying a billable order.')
            if not self.instance:attrs['billable']=False
        return attrs

    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), default=Decimal("1")
    )
    results = serializers.SerializerMethodField()

    @extend_schema_field(OrderResultSerializer(many=True))
    def get_results(self, instance):
        # Viewsets prefetch the same request-scoped queryset. Keep standalone
        # serialization (including create/update responses) fail-closed too.
        results = getattr(instance, '_visible_results', None)
        if results is None:
            user = getattr(self.context.get('request'), 'user', None)
            results = filter_visible_results(instance.results.all(), user)
        return OrderResultSerializer(results, many=True, context=self.context).data

    class Meta:
        model = Order
        fields = "__all__"
        read_only_fields = ("status", "created_at")
