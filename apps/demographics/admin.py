from django.contrib import admin
from .models import Patient

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'first_name',
        'last_name',
        'gender',
        'phone',
        'consent_data_processing',
        'consent_recorded_at',
        'data_retention_until',
        'created_at',
    )
    search_fields = ('first_name', 'last_name', 'phone', 'insurance_id')
    list_filter = ('gender', 'consent_data_processing')
