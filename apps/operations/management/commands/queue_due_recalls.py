from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.operations.models import PatientRecall
from apps.operations.outreach_services import queue_recall


class Command(BaseCommand):
    help = 'Preview recalls due soon; --commit queues consented notices and overdue owner tasks. Does not send messages.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=3)
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        days = options['days']
        if not 0 <= days <= 30:
            raise CommandError('--days must be between 0 and 30.')
        rows = PatientRecall.objects.filter(status='open', patient__merged_into__isnull=True, due_on__lte=timezone.localdate()+timedelta(days=days))
        self.stdout.write(f'{rows.count()} eligible recalls; mode: {"queue" if options["commit"] else "preview"}.')
        if options['commit']:
            for pk in rows.values_list('pk', flat=True).iterator():
                queue_recall(pk, days)
