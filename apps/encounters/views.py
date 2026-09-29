from rest_framework import viewsets
from common.permissions import RolePermission
from common.facility_scope import filter_by_facility, filter_by_encounter_facility, filter_by_patient_facility
from .models import Encounter, Vital, Diagnosis
from .serializers import EncounterSerializer, VitalSerializer, DiagnosisSerializer

class EncounterViewSet(viewsets.ModelViewSet):
    queryset = Encounter.objects.all().order_by('-id')
    serializer_class = EncounterSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','nurse','clinician'],
        'PUT': ['admin','nurse','clinician'],
        'PATCH': ['admin','nurse','clinician'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_facility(super().get_queryset(), self.request.user)

class VitalViewSet(viewsets.ModelViewSet):
    queryset = Vital.objects.all().order_by('-taken_at')
    serializer_class = VitalSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','nurse'],
        'PUT': ['admin','nurse'],
        'PATCH': ['admin','nurse'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_encounter_facility(super().get_queryset(), self.request.user)

class DiagnosisViewSet(viewsets.ModelViewSet):
    queryset = Diagnosis.objects.all().order_by('-id')
    serializer_class = DiagnosisSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','clinician'],
        'PUT': ['admin','clinician'],
        'PATCH': ['admin','clinician'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_encounter_facility(super().get_queryset(), self.request.user)
