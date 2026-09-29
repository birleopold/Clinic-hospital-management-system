from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import InventoryItemViewSet, BatchViewSet, StockMovementViewSet

router = DefaultRouter()
router.register(r'inventory/items', InventoryItemViewSet, basename='inventory-item')
router.register(r'inventory/batches', BatchViewSet, basename='batch')
router.register(r'inventory/movements', StockMovementViewSet, basename='movement')

urlpatterns = [
    path('', include(router.urls)),
]
