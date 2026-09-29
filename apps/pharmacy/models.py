from django.db import models
from simple_history.models import HistoricalRecords


class Prescription(models.Model):
    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    clinician = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    encounter = models.ForeignKey('encounters.Encounter', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Rx {self.id} for {self.patient}"


class PrescriptionItem(models.Model):
    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        from decimal import Decimal
        quantity=Decimal(str(self.quantity))
        dispensed=Decimal(str(self.dispensed_quantity))
        if not quantity.is_finite() or quantity <= 0 or quantity < dispensed:
            raise ValidationError('Prescription quantity must be positive and cover quantities already dispensed.')
        if self.pk:
            previous=type(self).objects.get(pk=self.pk)
            if previous.dispensed_quantity and (previous.item_code!=self.item_code or previous.prescription_id!=self.prescription_id):
                raise ValidationError('Cannot change a dispensed prescription line to a different medicine or prescription.')
        return super().save(*args, **kwargs)

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=64)
    item_name = models.CharField(max_length=255, blank=True)
    dose = models.CharField(max_length=128, blank=True)
    frequency = models.CharField(max_length=128, blank=True)
    duration = models.CharField(max_length=128, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    dispensed_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.item_code} x{self.quantity} (Rx {self.prescription_id})"


class Dispense(models.Model):
    def save(self, *args, **kwargs):
        from .services import save_dispense
        return save_dispense(self, *args, **kwargs)

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='dispenses')
    batch = models.ForeignKey('inventory.Batch', on_delete=models.SET_NULL, null=True, blank=True, related_name='dispenses')
    item_code = models.CharField(max_length=64)
    item_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    dispensed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.item_code} x{self.quantity}"


class Backorder(models.Model):
    OPEN = 'open'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (OPEN, 'Open'),
        (CLOSED, 'Closed'),
    ]
    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='backorders')
    item_code = models.CharField(max_length=64)
    item_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    fulfilled_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def remaining(self):
        return (self.quantity or 0) - (self.fulfilled_quantity or 0)

    def __str__(self):
        return f"BO {self.item_code} x{self.quantity} ({self.status})"
