from django.contrib import admin
from .models import Dispense, Prescription, PrescriptionItem, Backorder

@admin.register(Dispense)
class DispenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'item_code', 'quantity', 'dispensed_at')
    search_fields = ('item_code', 'item_name', 'patient__first_name', 'patient__last_name')


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('id','patient','clinician','created_at')
    search_fields = ('patient__first_name','patient__last_name','clinician__username')


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = ('id','prescription','item_code','quantity','dispensed_quantity')
    search_fields = ('item_code','item_name')


@admin.register(Backorder)
class BackorderAdmin(admin.ModelAdmin):
    list_display = ('id','patient','item_code','quantity','fulfilled_quantity','status','created_at')
    list_filter = ('status',)
    search_fields = ('item_code','item_name','patient__first_name','patient__last_name')
