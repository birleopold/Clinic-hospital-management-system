from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from apps.demographics.models import Patient
from apps.operations.models import Reminder, ReminderAttempt
from apps.operations.outreach_services import consent_valid


class Command(BaseCommand):
    help = 'Dispatch currently consented reminders. Provider acceptance does not prove handset delivery.'

    def handle(self, *args, **options):
        path = settings.INTEGRATIONS_SMS_BACKEND
        if path in ('apps.integrations.backends.NoOpSmsBackend', 'apps.integrations.backends.LogSmsBackend'):
            raise CommandError('Configure a real SMS backend; sandbox/no-op delivery is never marked sent.')
        backend = import_string(path)()
        if not getattr(backend, 'supports_idempotency', False):
            raise CommandError('SMS backend must support idempotency_key to safely retry delivery.')
        accepted = 0
        ids = list(Reminder.objects.filter(status='pending', scheduled_for__lte=timezone.now()).order_by('scheduled_for', 'pk').values_list('pk', flat=True)[:100])
        for pk in ids:
            with transaction.atomic():
                initial = Reminder.objects.get(pk=pk)
                Patient.objects.select_for_update().get(pk=initial.patient_id)
                job = Reminder.objects.select_for_update().select_related('patient').get(pk=pk)
                if job.status != 'pending':
                    continue
                if job.patient_id != initial.patient_id or not consent_valid(job) or job.attempts >= 3 or job.delivery_attempts.filter(outcome__in=['review', 'processing']).exists():
                    job.status = 'failed'
                    job.last_error = 'Current verified consent required, attempt limit reached, or prior outcome needs reconciliation.'
                    job.save()
                    continue
                job.status = 'processing'
                job.attempts += 1
                job.save()
                attempt = ReminderAttempt.objects.create(reminder=job)
                phone, body = job.patient.phone, job.body
            # Never hold database locks across an external network call. Opt-out prevents
            # subsequent claims; a provider request already claimed cannot be recalled.
            outcome, reference = 'review', ''
            detail = 'Uncertain provider outcome. Reconcile using the reminder idempotency key; do not blindly resend.'
            try:
                result = backend.send(phone, body, idempotency_key=f'reminder:{pk}')
                if result.get('ok') and result.get('ref'):
                    outcome, reference, detail = 'accepted', str(result['ref'])[:160], ''
                elif result.get('definitive_failure') is True and result.get('ok') is False:
                    outcome, detail = 'failed', 'Provider explicitly confirmed non-acceptance.'
            except Exception:
                pass  # No raw provider responses, phone numbers or credentials in the audit.
            with transaction.atomic():
                job = Reminder.objects.select_for_update().get(pk=pk)
                attempt.ended_at = timezone.now()
                attempt.outcome, attempt.provider_reference, attempt.detail = outcome, reference, detail
                attempt.save()
                job.status = 'sent' if outcome == 'accepted' else 'failed'
                job.provider_reference, job.last_error = reference, detail
                if outcome == 'accepted':
                    job.sent_at = attempt.ended_at
                    accepted += 1
                job.save()
        self.stdout.write(f'{accepted} reminders accepted by provider. Interrupted processing jobs require manual provider reconciliation.')
