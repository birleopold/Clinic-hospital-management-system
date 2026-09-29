from django.contrib import admin
from .models import (
    InventoryItem, Batch, StockMovement,
    Supplier, PurchaseOrder, PurchaseOrderLine,
    GoodsReceipt, GoodsReceiptLine,
)

class LedgerReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

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


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('id','supplier','ordered_date','status')
    list_filter = ('status',)
    inlines = [PurchaseOrderLineInline]


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 0


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(LedgerReadOnlyAdmin):
    list_display = ('id','po','received_at','posted','reference')
    list_filter = ('posted',)
    inlines = [GoodsReceiptLineInline]

