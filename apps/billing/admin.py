from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from common.admin import WorkflowReadOnlyAdmin, WorkflowReadOnlyInline
from common.facility_scope import filter_by_facility, filter_by_patient_facility
from .models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment, ClinicConfig, CashSession

@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ('id','name','is_active','effective_date')

@admin.register(PriceListItem)
class PriceListItemAdmin(admin.ModelAdmin):
    list_display = ('id','pricelist','code','name','amount','active')
    list_filter = ('pricelist','active')
    search_fields = ('code','name')

class InvoiceLineInline(WorkflowReadOnlyInline):
    model = InvoiceLine
    extra = 0

@admin.register(Invoice)
class InvoiceAdmin(WorkflowReadOnlyAdmin):
    list_display = ('id','patient','total_amount','paid_amount','status','created_at')
    inlines = [InvoiceLineInline]
    readonly_fields = ('workflow',)

    def get_queryset(self, request):
        return filter_by_patient_facility(super().get_queryset(request), request.user)

    @admin.display(description='Billing workflow')
    def workflow(self, obj):
        return format_html(
            '<a href="{}">Open invoice and reconciliation</a> · '
            '<a href="{}?invoice={}">Request a controlled invoice credit</a>',
            reverse('suite-invoice-detail', args=[obj.pk]),
            reverse('suite-collection', args=['credits']), obj.pk,
        )

@admin.register(Payment)
class PaymentAdmin(WorkflowReadOnlyAdmin):
    list_display = ('id','invoice','amount','method','paid_at')

    def get_queryset(self, request):
        return filter_by_patient_facility(super().get_queryset(request), request.user, prefix='invoice__patient__')

@admin.register(ClinicConfig)
class ClinicConfigAdmin(admin.ModelAdmin):
    list_display = ('id','clinic_name','receipt_paper')

@admin.register(CashSession)
class CashSessionAdmin(WorkflowReadOnlyAdmin):
    list_display = ('id','opened_by','open_time','close_time','opening_float','expected_cash','counted_cash','discrepancy')
    list_filter = ('opened_by',)

    readonly_fields = ('workflow',)

    def get_queryset(self, request):
        return filter_by_facility(
            super().get_queryset(request), request.user,
            field='opened_by__staff_profile__facility_id',
        )

    @admin.display(description='Cash reconciliation')
    def workflow(self, obj):
        return format_html(
            '<a href="{}">Open cash session report</a>',
            reverse('cash-session-report-id', args=[obj.pk]),
        )
