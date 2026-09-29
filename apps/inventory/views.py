from common.facility_scope import filter_by_facility
from rest_framework import viewsets, filters
from common.permissions import RolePermission
from .models import InventoryItem, Batch, StockMovement
from .serializers import InventoryItemSerializer, BatchSerializer, StockMovementSerializer

class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.all().order_by('code')
    serializer_class = InventoryItemSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['code','name']
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','pharmacy'],
        'PUT': ['admin','pharmacy'],
        'PATCH': ['admin','pharmacy'],
        'DELETE': ['admin'],
    }

class BatchViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        return filter_by_facility(super().get_queryset(), self.request.user, field="location__facility_id")

    queryset = Batch.objects.all().order_by('expiry')
    serializer_class = BatchSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','pharmacy'],
        'PUT': ['admin','pharmacy'],
        'PATCH': ['admin','pharmacy'],
        'DELETE': ['admin'],
    }

class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        return filter_by_facility(super().get_queryset(), self.request.user, field="batch__location__facility_id")

    queryset = StockMovement.objects.all().order_by('-created_at')
    serializer_class = StockMovementSerializer
