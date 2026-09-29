from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from apps.operations.models import Reminder

class Command(BaseCommand):
    help = 'Dispatch consented reminders using a configured idempotent SMS provider. Run under a supervised scheduler.'
    def handle(self, *args, **options):
        backend_path = settings.INTEGRATIONS_SMS_BACKEND
        if backend_path in ('apps.integrations.backends.NoOpSmsBackend','apps.integrations.backends.LogSmsBackend'):
            raise CommandError('Configure a real SMS backend; sandbox/no-op delivery is never marked sent.')
        backend = import_string(backend_path)()
        if not getattr(backend, 'supports_idempotency', False):
            raise CommandError('SMS backend must support idempotency_key to safely retry delivery.')
        sent = 0
        ids = Reminder.objects.filter(status='pending',scheduled_for__lte=timezone.now()).values_list('pk',flat=True)[:100]
        for pk in list(ids):
            with transaction.atomic():
                job = Reminder.objects.select_for_update().get(pk=pk)
                if job.status != 'pending': continue
                if not job.consent_confirmed or not job.patient.phone:
                    job.status='failed';job.last_error='Consent or phone missing';job.save();continue
                job.status='processing';job.attempts+=1;job.save()
            try:
                result=backend.send(job.patient.phone,job.body,idempotency_key=f'reminder:{job.pk}')
                if not result.get('ok') or not result.get('ref'):
                    raise ValueError('Provider did not confirm acceptance')
                job.status='sent';job.provider_reference=str(result['ref'])[:160];job.sent_at=timezone.now();job.last_error=''
                sent+=1
            except Exception:
                job.status='failed';job.last_error='Provider delivery failed; inspect provider logs using the job reference.'
            job.save()
        self.stdout.write(f'{sent} reminders accepted by provider. Processing jobs after an interrupted worker require reconciliation before retry.')
