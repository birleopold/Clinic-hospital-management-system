from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import EncounterViewSet, VitalViewSet, DiagnosisViewSet

router = DefaultRouter()
router.register(r'encounters', EncounterViewSet, basename='encounter')
router.register(r'vitals', VitalViewSet, basename='vital')
router.register(r'diagnoses', DiagnosisViewSet, basename='diagnosis')

urlpatterns = [
    path('', include(router.urls)),
]
