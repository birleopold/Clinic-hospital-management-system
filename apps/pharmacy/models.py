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
