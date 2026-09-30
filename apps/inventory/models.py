from django.db import models
from simple_history.models import HistoricalRecords

class InventoryItem(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    uom = models.CharField(max_length=32, default='unit')
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.code} - {self.name}"

class Batch(models.Model):
    location = models.ForeignKey('operations.StockLocation', null=True, blank=True, on_delete=models.PROTECT)
    quarantined = models.BooleanField(default=False)

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='batches')
    batch_no = models.CharField(max_length=64, blank=True)
    expiry = models.DateField(null=True, blank=True)
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.item.code} {self.batch_no or ''}"

class StockMovement(models.Model):
    IN = 'in'
    OUT = 'out'
    ADJUST = 'adjust'
    DIR_CHOICES = [
        (IN, 'In'),
        (OUT, 'Out'),
        (ADJUST, 'Adjust'),
    ]
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='movements')
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    direction = models.CharField(max_length=8, choices=DIR_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=64, blank=True)
    ref = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.direction} {self.item.code} x{self.quantity}"


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=128, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    created_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    approved_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)

    facility = models.ForeignKey("accounts.Facility", null=True, blank=True, on_delete=models.PROTECT)

    DRAFT = 'draft'
    APPROVED = 'approved'
    RECEIVED = 'received'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (APPROVED, 'Approved'),
        (RECEIVED, 'Received'),
        (CANCELLED, 'Cancelled'),
    ]
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    ordered_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=DRAFT)
    remarks = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"PO#{self.id} - {self.supplier} ({self.status})"


class PurchaseOrderLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    quantity_ordered = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.po_id}:{self.item.code} x{self.quantity_ordered}"


class GoodsReceipt(models.Model):
    location = models.ForeignKey("operations.StockLocation", null=True, blank=True, on_delete=models.PROTECT)

    po = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name='receipts')
    received_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=128, blank=True)
    posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"GRN#{self.id} for PO#{self.po_id}"


class GoodsReceiptLine(models.Model):
    grn = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='lines')
    po_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipt_lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    batch_no = models.CharField(max_length=64, blank=True)
    expiry = models.DateField(null=True, blank=True)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    history = HistoricalRecords()

    def __str__(self):
        return f"GRN{self.grn_id}:{self.item.code} x{self.quantity_received}"
