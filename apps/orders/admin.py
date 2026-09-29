from django.contrib import admin
from .models import Order, OrderResult

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'encounter', 'order_type', 'code', 'quantity', 'status', 'created_at')
    search_fields = ('code', 'description', 'patient__first_name', 'patient__last_name')
    list_filter = ('order_type', 'status')

@admin.register(OrderResult)
class OrderResultAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
    list_display = ('id','order','recorded_at')
