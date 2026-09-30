import uuid
from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class OfflineDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    facility = models.ForeignKey("accounts.Facility", on_delete=models.PROTECT)
    label = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()


class OfflineReceipt(models.Model):
    client_created_at = models.DateTimeField(null=True, blank=True)
    device = models.ForeignKey(OfflineDevice, on_delete=models.PROTECT)
    client_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    model_label = models.CharField(max_length=100)
    record_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "client_id"], name="unique_offline_submission"
            )
        ]
