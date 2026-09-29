from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import DispenseViewSet, PrescriptionViewSet, PrescriptionItemViewSet

router = DefaultRouter()
router.register(r'dispenses', DispenseViewSet, basename='dispense')
router.register(r'prescriptions', PrescriptionViewSet, basename='prescription')
router.register(r'prescription-items', PrescriptionItemViewSet, basename='prescription-item')

urlpatterns = [
    path('', include(router.urls)),
]
