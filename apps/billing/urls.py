from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import PriceListItemViewSet, InvoiceViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r'pricelist-items', PriceListItemViewSet, basename='pricelist-item')
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'payments', PaymentViewSet, basename='payment')

urlpatterns = [
    path('', include(router.urls)),
]
