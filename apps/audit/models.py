from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=64, blank=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=512)
    status_code = models.PositiveIntegerField()
    remote_addr = models.CharField(max_length=64, blank=True)
    user_agent = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["status_code"]),
            models.Index(fields=["method"]),
        ]

    def __str__(self):
        return f"{self.method} {self.path} {self.status_code}"
