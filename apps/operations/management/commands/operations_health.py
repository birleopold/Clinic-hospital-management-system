import json
from datetime import timedelta
from django.db import connection
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from apps.operations.models import Reminder, PaymentIntent, LoginThrottle
from apps.audit.models import AuditEvent


class Command(BaseCommand):
    help = "Emit operational health counters; nonzero exit when exceptions require attention."

    def add_arguments(self, parser):
        parser.add_argument("--cleanup-throttles", action="store_true")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        cutoff = timezone.now() - timedelta(minutes=15)
        if options["cleanup_throttles"]:
            LoginThrottle.objects.filter(
                window_start__lt=timezone.now() - timedelta(days=2)
            ).delete()
        report = {
            "database": "ok",
            "failed_reminders": Reminder.objects.filter(status="failed").count(),
            "stuck_reminders": Reminder.objects.filter(
                status="processing", created_at__lt=cutoff
            ).count(),
            "collections_needing_review": PaymentIntent.objects.filter(
                status="review"
            ).count(),
            "recent_server_errors": AuditEvent.objects.filter(
                created_at__gte=cutoff, status_code__gte=500
            ).count(),
        }
        self.stdout.write(json.dumps(report))
        if any(value for key, value in report.items() if key != "database"):
            raise CommandError("Operational exceptions need attention.")
