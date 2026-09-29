from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, OrderResultViewSet

router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'order-results', OrderResultViewSet, basename='order-result')

urlpatterns = [
    path('', include(router.urls)),
]
