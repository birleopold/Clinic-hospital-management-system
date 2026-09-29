from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import RolePermission
from common.facility_scope import filter_by_patient_facility
from .models import Order, OrderResult
from .serializers import OrderSerializer, OrderResultSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().prefetch_related('results').order_by('-created_at', '-id')
    serializer_class = OrderSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin', 'clinician', 'lab'],
        'PUT': ['admin', 'clinician', 'lab'],
        'PATCH': ['admin', 'clinician', 'lab'],
        'DELETE': ['admin'],
        'cancel': ['admin', 'clinician', 'lab'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(super().get_queryset(), self.request.user)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.ORDERED:
            return Response(
                {'detail': 'Only pending (ordered) orders can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.CANCELLED
        order.save(update_fields=['status'])
        return Response(self.get_serializer(order).data)


class OrderResultViewSet(viewsets.ModelViewSet):
    queryset = OrderResult.objects.all().select_related('order').order_by('-recorded_at', '-id')
    serializer_class = OrderResultSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin', 'clinician', 'lab'],
        'PUT': ['admin', 'lab'],
        'PATCH': ['admin', 'lab'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(
            super().get_queryset(),
            self.request.user,
            prefix='order__patient__',
        )
