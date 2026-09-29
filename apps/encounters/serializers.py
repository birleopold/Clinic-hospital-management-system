from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from .models import Encounter, Vital, Diagnosis

class VitalSerializer(FacilityScopedSerializer):
    class Meta:
        model = Vital
        fields = '__all__'

class DiagnosisSerializer(FacilityScopedSerializer):
    class Meta:
        model = Diagnosis
        fields = '__all__'

class EncounterSerializer(FacilityScopedSerializer):
    vitals = VitalSerializer(many=True, read_only=True)
    diagnoses = DiagnosisSerializer(many=True, read_only=True)

    class Meta:
        model = Encounter
        fields = ('id','patient','clinician','started_at','ended_at','status','chief_complaint','notes','vitals','diagnoses')
