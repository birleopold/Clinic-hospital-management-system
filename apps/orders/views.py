from django.db.models import Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import RolePermission
from common.facility_scope import filter_by_patient_facility
from .models import Order, OrderResult
from .permissions import filter_visible_results
from .serializers import OrderSerializer, OrderResultSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().order_by('-created_at', '-id')
    serializer_class = OrderSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','clinician','lab','nurse'],
        'POST': ['admin', 'clinician', 'lab'],
        'PUT': ['admin', 'clinician', 'lab'],
        'PATCH': ['admin', 'clinician', 'lab'],
        'DELETE': ['admin'],
        'cancel': ['admin', 'clinician', 'lab'],
    }

    def get_queryset(self):
        from common.service_policy import enabled
        qs=filter_by_patient_facility(super().get_queryset(), self.request.user)
        if not enabled(self.request.user,'lab'):qs=qs.exclude(order_type='lab')
        if not enabled(self.request.user,'imaging'):qs=qs.exclude(order_type='imaging')
        if not enabled(self.request.user,'clinical'):qs=qs.exclude(order_type='procedure')
        return qs.prefetch_related(Prefetch(
            'results',
            queryset=filter_visible_results(OrderResult.objects.all(), self.request.user),
            to_attr='_visible_results',
        ))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from .services import cancel_order
        from django.core.exceptions import ValidationError
        order = self.get_object()
        try:order=cancel_order(order.pk,request.user)
        except ValidationError as exc:return Response({'detail':exc.messages},status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)



class OrderResultViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)
    queryset = OrderResult.objects.all().select_related('order').order_by('-recorded_at', '-id')
    serializer_class = OrderResultSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','clinician','lab','nurse'],
        'POST': ['admin', 'clinician', 'lab'],
        'PUT': ['admin', 'lab'],
        'PATCH': ['admin', 'lab'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_visible_results(super().get_queryset(), self.request.user)
