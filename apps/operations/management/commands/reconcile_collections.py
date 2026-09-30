from django.core.management.base import BaseCommand, CommandError
from apps.operations.models import PaymentIntent
from apps.integrations.providers import MTNCollection
from apps.integrations.collections import reconcile_collection


class Command(BaseCommand):
    help = "Poll MTN and reconcile unresolved collection references without initiating new payments."

    def handle(self, *args, **options):
        provider = MTNCollection()
        failures = 0
        for pk in PaymentIntent.objects.filter(
            status__in=["requested", "review"], payment__isnull=True
        ).values_list("pk", flat=True)[:100]:
            try:
                reconcile_collection(pk, provider)
            except Exception:
                failures += 1
                PaymentIntent.objects.filter(pk=pk).update(
                    last_error="Provider status unavailable; retry reconciliation."
                )
        if failures:
            raise CommandError(f"{failures} provider status checks failed.")
        self.stdout.write("Collection reconciliation completed.")
