import csv
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.billing.models import Payment
from apps.demographics.models import Patient
from apps.encounters.models import Encounter


class Command(BaseCommand):
    help = (
        'Export daily operational counts (new patients, encounters started, '
        'appointments scheduled, payment totals) as CSV.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of calendar days ending today (default 30).',
        )
        parser.add_argument(
            '--output',
            '-o',
            help='Write to this file; default is stdout.',
        )

    def handle(self, *args, **options):
        days = max(1, options['days'])
        out_path = options.get('output')
        end = timezone.localdate()
        start = end - timedelta(days=days - 1)

        fieldnames = [
            'date',
            'patients_registered',
            'encounters_started',
            'appointments_scheduled',
            'payment_total',
            'payment_count',
        ]

        stream = open(out_path, 'w', newline='', encoding='utf-8') if out_path else sys.stdout
        close_stream = bool(out_path)
        try:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for i in range(days):
                d = start + timedelta(days=i)
                pay_qs = Payment.objects.filter(paid_at__date=d)
                total = pay_qs.aggregate(s=Sum('amount'))['s']
                writer.writerow(
                    {
                        'date': d.isoformat(),
                        'patients_registered': Patient.objects.filter(created_at__date=d).count(),
                        'encounters_started': Encounter.objects.filter(started_at__date=d).count(),
                        'appointments_scheduled': Appointment.objects.filter(scheduled_for__date=d).count(),
                        'payment_total': str(total) if total is not None else '',
                        'payment_count': pay_qs.count(),
                    }
                )
        finally:
            if close_stream:
                stream.close()

        if out_path:
            self.stdout.write(self.style.SUCCESS(f'Wrote {out_path}'))
