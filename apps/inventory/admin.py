from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from common.admin import WorkflowReadOnlyAdmin, WorkflowReadOnlyInline
from common.facility_scope import filter_by_facility
from .models import (
    InventoryItem, Batch, StockMovement,
    Supplier, PurchaseOrder, PurchaseOrderLine,
    GoodsReceipt, GoodsReceiptLine,
)

class LedgerReadOnlyAdmin(WorkflowReadOnlyAdmin):
    pass

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('id','code','name','uom','reorder_level','created_at')
    search_fields = ('code','name')

@admin.register(Batch)
class BatchAdmin(LedgerReadOnlyAdmin):
    list_display = ('id','item','batch_no','expiry','quantity_on_hand')
    list_filter = ('expiry',)

@admin.register(StockMovement)
class StockMovementAdmin(LedgerReadOnlyAdmin):
    list_display = ('id','item','direction','quantity','reason','ref','created_at')
    list_filter = ('direction',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('id','name','phone','email','created_at')
    search_fields = ('name','phone','email')


class PurchaseOrderLineInline(WorkflowReadOnlyInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(LedgerReadOnlyAdmin):
    list_display = ('id','supplier','ordered_date','status')
    list_filter = ('status',)
    inlines = [PurchaseOrderLineInline]
    readonly_fields = ('workflow',)

    def get_queryset(self, request):
        return filter_by_facility(super().get_queryset(request), request.user)

    @admin.display(description='Purchasing workflow')
    def workflow(self, obj):
        return format_html(
            '<a href="{}">Open purchase order for controlled editing and approval</a>',
            reverse('inventory-po-edit', args=[obj.pk]),
        )


class GoodsReceiptLineInline(WorkflowReadOnlyInline):
    model = GoodsReceiptLine
    extra = 0


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(LedgerReadOnlyAdmin):
    list_display = ('id','po','received_at','posted','reference')
    list_filter = ('posted',)
    inlines = [GoodsReceiptLineInline]
    readonly_fields = ('workflow',)

    def get_queryset(self, request):
        return filter_by_facility(super().get_queryset(request), request.user, field='po__facility_id')

    @admin.display(description='Receiving workflow')
    def workflow(self, obj):
        return format_html(
            '<a href="{}">Open goods receipt for controlled posting</a>',
            reverse('inventory-grn-detail', args=[obj.pk]),
        )

