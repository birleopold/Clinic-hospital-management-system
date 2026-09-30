"""Catalog metadata and audited, patient-bound dispensing baskets."""
import uuid
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords


class MedicineProfile(models.Model):
    item = models.OneToOneField('inventory.InventoryItem', on_delete=models.PROTECT, related_name='medicine')
    generic_name = models.CharField(max_length=200, blank=True)
    ingredients = models.CharField(max_length=500, blank=True, help_text='Include each active ingredient and its strength for combination products.')
    strength = models.CharField(max_length=120, blank=True)
    dosage_form = models.CharField(max_length=80, blank=True)
    route = models.CharField(max_length=80, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    prescription_required = models.BooleanField(default=True)
    reviewed = models.BooleanField(default=False, help_text='Confirm the catalog entry and dispensing classification have been reviewed.')
    active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return str(self.item)


class MedicineBarcode(models.Model):
    code = models.CharField(max_length=100, unique=True)
    item = models.ForeignKey('inventory.InventoryItem', on_delete=models.PROTECT, related_name='barcodes')
    package = models.ForeignKey('operations.PackageUnit', on_delete=models.PROTECT, null=True, blank=True)
    active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def clean(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.models import InventoryItem
        if self.package_id and self.package.item_id != self.item_id:
            raise ValidationError('The package must belong to this medicine.')
        if InventoryItem.objects.filter(code=self.code).exclude(pk=self.item_id).exists():
            raise ValidationError('This barcode conflicts with another inventory code.')
        if self.package_id and InventoryItem.objects.filter(code=self.code).exists():
            raise ValidationError('Use a distinct package barcode; inventory codes always mean base units.')

    def __str__(self):
        return self.code


class PharmacyPolicy(models.Model):
    facility = models.OneToOneField('accounts.Facility', on_delete=models.PROTECT)
    allow_retail = models.BooleanField(default=False, help_text='Permit reviewed non-prescription catalog items without an Rx at this facility.')
    history = HistoricalRecords()


class DispensingBasket(models.Model):
    patient = models.ForeignKey('demographics.Patient', on_delete=models.PROTECT)
    created_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=16, default='open', choices=[('open','Open'),('held','Held'),('completed','Dispensed'),('cancelled','Cancelled')])
    revision = models.PositiveIntegerField(default=1)
    checkout_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invoice = models.OneToOneField('billing.Invoice', on_delete=models.PROTECT, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    history = HistoricalRecords()

    class Meta:
        indexes = [models.Index(fields=['status','updated_at'])]


class BasketLine(models.Model):
    basket = models.ForeignKey(DispensingBasket, on_delete=models.PROTECT, related_name='lines')
    item = models.ForeignKey('inventory.InventoryItem', on_delete=models.PROTECT)
    prescription_item = models.ForeignKey('pharmacy.PrescriptionItem', on_delete=models.PROTECT, null=True, blank=True)
    package = models.ForeignKey('operations.PackageUnit', on_delete=models.PROTECT, null=True, blank=True)
    package_name = models.CharField(max_length=80, default='Base units')
    units_per_pack = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    packs = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    medicine_snapshot = models.JSONField(default=dict)
    prescription_snapshot = models.JSONField(default=dict, blank=True)
    instructions = models.TextField(blank=True)
    removed = models.BooleanField(default=False)
    history = HistoricalRecords()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0, packs__gt=0, units_per_pack__gt=0, unit_price__gte=0), name='basket_line_positive_values')]

    @property
    def total(self):
        from decimal import Decimal, ROUND_HALF_UP
        return (self.quantity*self.unit_price).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


class BasketAllocation(models.Model):
    line = models.ForeignKey(BasketLine, on_delete=models.PROTECT, related_name='allocations')
    dispense = models.OneToOneField('pharmacy.Dispense', on_delete=models.PROTECT)
    history = HistoricalRecords()
