from django.contrib import admin
from .models import Encounter, Vital, Diagnosis

@admin.register(Encounter)
class EncounterAdmin(admin.ModelAdmin):
    list_display = ('id','patient','clinician','status','started_at','ended_at')
    list_filter = ('status',)
    search_fields = ('patient__first_name','patient__last_name','chief_complaint')

@admin.register(Vital)
class VitalAdmin(admin.ModelAdmin):
    list_display = ('id','encounter','temperature_c','pulse','systolic','diastolic','taken_at')

@admin.register(Diagnosis)
class DiagnosisAdmin(admin.ModelAdmin):
    list_display = ('id', 'encounter', 'code', 'coding_system', 'description', 'is_primary')
    list_filter = ('coding_system', 'is_primary')
