import csv
from calendar import monthrange
import datetime as dt
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum
from django.utils import timezone

from apps.billing.models import InvoiceLine
from apps.demographics.models import Patient
from apps.encounters.models import Diagnosis, Encounter


def _month_bounds(year: int, month: int):
    tz = timezone.get_current_timezone()
    last = monthrange(year, month)[1]
    first_d = dt.date(year, month, 1)
    last_d = dt.date(year, month, last)
    start = timezone.make_aware(dt.datetime.combine(first_d, dt.time.min), tz)
    end = timezone.make_aware(dt.datetime.combine(last_d, dt.time.max), tz)
    return start, end


class Command(BaseCommand):
    help = (
        'Write HMIS-oriented CSV files for a calendar month: new patients, OPD visits, '
        'diagnoses, revenue by service code, and diagnosis mix.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True, choices=range(1, 13))
        parser.add_argument(
            '--output-dir',
            '-o',
            required=True,
            help='Directory to create (must not exist, or use --force).',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Allow writing into an existing directory.',
        )

    def handle(self, *args, **options):
        year, month = options['year'], options['month']
        out_root = Path(options['output_dir'])
        if out_root.exists() and not options['force']:
            raise CommandError(f'Directory exists: {out_root} (pass --force to overwrite files inside)')
        out_root.mkdir(parents=True, exist_ok=True)

        start, end = _month_bounds(year, month)
        sub = f'{year:04d}-{month:02d}'
        self.stdout.write(f'Export window (local TZ): {start.isoformat()} .. {end.isoformat()}')

        # 01 — New patient registrations (demographics)
        p_path = out_root / f'01_new_patients_{sub}.csv'
        new_patients = Patient.objects.filter(created_at__gte=start, created_at__lte=end).order_by('id')
        with p_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    'patient_id',
                    'created_at',
                    'facility_id',
                    'first_name',
                    'last_name',
                    'gender',
                    'date_of_birth',
                    'phone',
                    'consent_data_processing',
                ],
            )
            w.writeheader()
            for p in new_patients.iterator():
                w.writerow(
                    {
                        'patient_id': p.id,
                        'created_at': p.created_at.isoformat() if p.created_at else '',
                        'facility_id': p.facility_id or '',
                        'first_name': p.first_name,
                        'last_name': p.last_name,
                        'gender': p.gender,
                        'date_of_birth': p.date_of_birth.isoformat() if p.date_of_birth else '',
                        'phone': p.phone,
                        'consent_data_processing': int(p.consent_data_processing),
                    }
                )

        # 02 — OPD-style visits (encounters started in month)
        e_path = out_root / f'02_opd_visits_{sub}.csv'
        enc_qs = Encounter.objects.filter(started_at__gte=start, started_at__lte=end).select_related(
            'patient', 'clinician', 'facility'
        )
        with e_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    'encounter_id',
                    'patient_id',
                    'facility_id',
                    'facility_name',
                    'clinician_id',
                    'started_at',
                    'ended_at',
                    'status',
                    'chief_complaint',
                ],
            )
            w.writeheader()
            for e in enc_qs.iterator():
                w.writerow(
                    {
                        'encounter_id': e.id,
                        'patient_id': e.patient_id,
                        'facility_id': e.facility_id or '',
                        'facility_name': getattr(e.facility, 'name', '') if e.facility_id else '',
                        'clinician_id': e.clinician_id or '',
                        'started_at': e.started_at.isoformat() if e.started_at else '',
                        'ended_at': e.ended_at.isoformat() if e.ended_at else '',
                        'status': e.status,
                        'chief_complaint': e.chief_complaint,
                    }
                )

        # 03 — Diagnoses linked to encounters in window
        d_path = out_root / f'03_diagnoses_{sub}.csv'
        dx_qs = (
            Diagnosis.objects.filter(encounter__started_at__gte=start, encounter__started_at__lte=end)
            .select_related('encounter')
            .order_by('id')
        )
        with d_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    'diagnosis_id',
                    'encounter_id',
                    'patient_id',
                    'coding_system',
                    'code',
                    'description',
                    'is_primary',
                    'encounter_started_at',
                ],
            )
            w.writeheader()
            for d in dx_qs.iterator():
                w.writerow(
                    {
                        'diagnosis_id': d.id,
                        'encounter_id': d.encounter_id,
                        'patient_id': d.encounter.patient_id,
                        'coding_system': d.coding_system,
                        'code': d.code,
                        'description': d.description,
                        'is_primary': int(d.is_primary),
                        'encounter_started_at': d.encounter.started_at.isoformat()
                        if d.encounter.started_at
                        else '',
                    }
                )

        # 04 — Service revenue by invoice line code (invoice created in month)
        r_path = out_root / f'04_revenue_by_service_code_{sub}.csv'
        lines = (
            InvoiceLine.objects.filter(invoice__created_at__gte=start, invoice__created_at__lte=end)
            .values('code')
            .annotate(line_count=Count('id'), qty_sum=Sum('quantity'), amount_sum=Sum('line_total'))
            .order_by('-amount_sum')
        )
        with r_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=['service_code', 'line_count', 'quantity_sum', 'line_total_sum'],
            )
            w.writeheader()
            for row in lines:
                w.writerow(
                    {
                        'service_code': row['code'],
                        'line_count': row['line_count'],
                        'quantity_sum': str(row['qty_sum'] or ''),
                        'line_total_sum': str(row['amount_sum'] or ''),
                    }
                )

        # 05 — Diagnosis mix (counts by coding system + code)
        m_path = out_root / f'05_diagnosis_mix_{sub}.csv'
        mix = (
            Diagnosis.objects.filter(encounter__started_at__gte=start, encounter__started_at__lte=end)
            .values('coding_system', 'code')
            .annotate(dx_count=Count('id'))
            .order_by('-dx_count')
        )
        with m_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['coding_system', 'code', 'diagnosis_count'])
            w.writeheader()
            for row in mix:
                w.writerow(
                    {
                        'coding_system': row['coding_system'],
                        'code': row['code'],
                        'diagnosis_count': row['dx_count'],
                    }
                )

        readme = out_root / 'README.txt'
        readme.write_text(
            f'HMIS monthly export for {sub}\n'
            f'Time zone: {timezone.get_current_timezone_name()}\n'
            f'See docs/HMIS_EXPORTS.md for column meanings.\n',
            encoding='utf-8',
        )

        self.stdout.write(self.style.SUCCESS(f'Wrote CSV bundle under {out_root.resolve()}'))
