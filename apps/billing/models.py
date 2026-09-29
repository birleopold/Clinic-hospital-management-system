from decimal import Decimal
from django.db import models
from simple_history.models import HistoricalRecords

class PriceList(models.Model):
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

class PriceListItem(models.Model):
    pricelist = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name='items')
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        unique_together = ('pricelist', 'code')

    def __str__(self):
        return f"{self.code} - {self.name}"

class ClinicConfig(models.Model):
    A4 = 'a4'
    R80 = '80mm'
    RECEIPT_PAPER_CHOICES = [
        (A4, 'A4 (210mm)'),
        (R80, 'Thermal 80mm')
    ]

    clinic_name = models.CharField(max_length=255, blank=True)
    receipt_paper = models.CharField(max_length=16, choices=RECEIPT_PAPER_CHOICES, default=A4)
    near_expiry_days = models.PositiveIntegerField(default=30)
    history = HistoricalRecords()

    def __str__(self):
        return f"Clinic Config ({self.clinic_name or 'Unnamed'})"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

class Invoice(models.Model):
    DRAFT = 'draft'
    READY = 'ready_to_pay'
    PAID = 'paid'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (READY, 'Ready to Pay'),
        (PAID, 'Paid'),
        (CANCELLED, 'Cancelled'),
    ]

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Invoice {self.id} - {self.patient}"

class CashSession(models.Model):
    opened_by = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='cash_sessions')
    open_time = models.DateTimeField(auto_now_add=True)
    close_time = models.DateTimeField(null=True, blank=True)
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discrepancy = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['-open_time']

    def __str__(self):
        status = 'OPEN' if not self.close_time else 'CLOSED'
        return f"Session #{self.id} {status} by {self.opened_by}"

class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    code = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    source_ref = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)

class Payment(models.Model):
    CASH = 'cash'
    METHOD_CHOICES = [
        (CASH, 'Cash'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    cash_session = models.ForeignKey('billing.CashSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=CASH)
    paid_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()
