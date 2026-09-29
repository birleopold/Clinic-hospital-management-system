from django.db import models
from simple_history.models import HistoricalRecords

class Order(models.Model):
    LAB = 'lab'
    IMAGING = 'imaging'
    PROCEDURE = 'procedure'

    ORDER_TYPE_CHOICES = [
        (LAB, 'Lab'),
        (IMAGING, 'Imaging'),
        (PROCEDURE, 'Procedure'),
    ]

    ORDERED = 'ordered'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (ORDERED, 'Ordered'),
        (COMPLETED, 'Completed'),
        (CANCELLED, 'Cancelled'),
    ]

    patient = models.ForeignKey('demographics.Patient', on_delete=models.CASCADE)
    encounter = models.ForeignKey(
        'encounters.Encounter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    order_type = models.CharField(max_length=16, choices=ORDER_TYPE_CHOICES)
    code = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=ORDERED)
    billable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.order_type}:{self.code} x{self.quantity}"


class OrderResult(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='results')
    result_text = models.TextField(blank=True)
    attachment = models.FileField(upload_to='order_results/', blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Result for {self.order_id} at {self.recorded_at}"
