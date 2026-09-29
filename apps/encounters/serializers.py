from rest_framework import serializers
from .models import Encounter, Vital, Diagnosis

class VitalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vital
        fields = '__all__'

class DiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diagnosis
        fields = '__all__'

class EncounterSerializer(serializers.ModelSerializer):
    vitals = VitalSerializer(many=True, read_only=True)
    diagnoses = DiagnosisSerializer(many=True, read_only=True)

    class Meta:
        model = Encounter
        fields = ('id','patient','clinician','started_at','ended_at','status','chief_complaint','notes','vitals','diagnoses')
