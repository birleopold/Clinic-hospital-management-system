from django.contrib import admin
from .models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment, ClinicConfig, CashSession

@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ('id','name','is_active','effective_date')

@admin.register(PriceListItem)
class PriceListItemAdmin(admin.ModelAdmin):
    list_display = ('id','pricelist','code','name','amount','active')
    list_filter = ('pricelist','active')
    search_fields = ('code','name')

class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id','patient','total_amount','paid_amount','status','created_at')
    inlines = [InvoiceLineInline]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id','invoice','amount','method','paid_at')

@admin.register(ClinicConfig)
class ClinicConfigAdmin(admin.ModelAdmin):
    list_display = ('id','clinic_name','receipt_paper')

@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = ('id','opened_by','open_time','close_time','opening_float','expected_cash','counted_cash','discrepancy')
    list_filter = ('opened_by',)
