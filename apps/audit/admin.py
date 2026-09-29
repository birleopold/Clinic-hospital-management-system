from django.contrib import admin
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "user", "role", "method", "path", "status_code", "duration_ms")
    list_filter = ("method", "status_code")
    search_fields = ("path", "user__username", "role")
    date_hierarchy = "created_at"
