"""Phase two approval and reconciliation records; original ledgers stay intact."""
from django.db import models
from django.db.models import Q
from .models import Record
from simple_history.models import HistoricalRecords


class PaymentRequest(Record):
    key = models.UUIDField(unique=True)
    invoice = models.ForeignKey('billing.Invoice', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    payment = models.OneToOneField('billing.Payment', on_delete=models.PROTECT)


class RefundAuthorization(Record):
    authorized_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,editable=False)
    payment_reference=models.PositiveBigIntegerField(null=True,editable=False)
    refund = models.OneToOneField('operations.Refund', on_delete=models.PROTECT, related_name='authorization')
    reason = models.CharField(max_length=250)


class MedicineReturn(Record):
    dispense = models.ForeignKey('pharmacy.Dispense', on_delete=models.PROTECT, related_name='returns')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    disposition = models.CharField(max_length=16, default='quarantine', choices=[('quarantine','Quarantine'),('restock','Return to usable stock'),('dispose','Dispose; do not restock')])
    reason = models.CharField(max_length=250)
    inspection = models.TextField(help_text='Record pack integrity, storage evidence and the basis for the disposition.')
    status = models.CharField(max_length=16, default='requested', choices=[('requested','Awaiting review'),('posted','Posted'),('rejected','Rejected')])
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250, blank=True)
    credit_line = models.OneToOneField('billing.InvoiceLine', on_delete=models.PROTECT, null=True)
    returned_batch = models.OneToOneField('inventory.Batch', on_delete=models.PROTECT, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints=[models.CheckConstraint(condition=Q(quantity__gt=0,amount__gte=0),name='valid_medicine_return_values')]


class ReturnRefundLink(models.Model):
    medicine_return = models.ForeignKey(MedicineReturn, on_delete=models.PROTECT, related_name='refund_links')
    refund = models.OneToOneField('operations.Refund', on_delete=models.PROTECT)


class PriceOverride(Record):
    line = models.ForeignKey('pharmacy.BasketLine', on_delete=models.PROTECT, related_name='price_reviews')
    catalog_price = models.DecimalField(max_digits=12, decimal_places=2)
    requested_price = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=16, default='requested', choices=[('requested','Awaiting review'),('approved','Approved'),('rejected','Rejected')])
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True)
    review_reason = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints=[models.CheckConstraint(condition=Q(requested_price__gte=0),name='positive_price_override'),models.UniqueConstraint(fields=['line'],condition=Q(status__in=['requested','approved']),name='one_active_price_review')]


class ReplenishmentRule(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    item = models.ForeignKey('inventory.InventoryItem', on_delete=models.PROTECT)
    preferred_location = models.ForeignKey('operations.StockLocation', on_delete=models.PROTECT, null=True, blank=True, help_text='Destination for within-facility transfer suggestions.')
    lead_days = models.PositiveSmallIntegerField(default=7)
    review_days = models.PositiveSmallIntegerField(default=7)
    safety_days = models.PositiveSmallIntegerField(default=7)
    history = HistoricalRecords()

    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','item'],name='unique_replenishment_rule')]
