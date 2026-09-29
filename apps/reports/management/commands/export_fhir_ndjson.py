import json
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.demographics.models import Patient
from apps.encounters.models import Encounter

_GENDER = {'M': 'male', 'F': 'female', 'O': 'other'}


def _local_day_bounds(d: dt.date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(dt.datetime.combine(d, dt.time.min), tz)
    end = timezone.make_aware(dt.datetime.combine(d, dt.time.max), tz)
    return start, end


def _patient_fhir(p: Patient) -> dict:
    r = {
        'resourceType': 'Patient',
        'id': f'patient-{p.pk}',
        'identifier': [{'system': 'urn:ug-hms:patient-id', 'value': str(p.pk)}],
        'name': [
            {
                'family': p.last_name,
                'given': [p.first_name] + ([p.other_names] if p.other_names else []),
            }
        ],
    }
    g = _GENDER.get(p.gender)
    if g:
        r['gender'] = g
    if p.date_of_birth:
        r['birthDate'] = p.date_of_birth.isoformat()
    return r


def _encounter_fhir(e: Encounter) -> dict:
    period = {'start': e.started_at.isoformat()}
    if e.ended_at:
        period['end'] = e.ended_at.isoformat()
    return {
        'resourceType': 'Encounter',
        'id': f'encounter-{e.pk}',
        'status': 'finished' if e.status == Encounter.CLOSED else 'in-progress',
        'class': {
            'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
            'code': 'AMB',
            'display': 'ambulatory',
        },
        'subject': {'reference': f'Patient/patient-{e.patient_id}'},
        'period': period,
    }


class Command(BaseCommand):
    help = (
        'Emit NDJSON lines of minimal FHIR R4 Patient and Encounter resources for encounters '
        'started in the date range (read-only pilot export).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--from-date', required=True, help='Inclusive start date YYYY-MM-DD (local TZ).')
        parser.add_argument('--to-date', required=True, help='Inclusive end date YYYY-MM-DD (local TZ).')
        parser.add_argument('--output', '-o', required=True, help='NDJSON output file path.')

    def handle(self, *args, **options):
        try:
            d0 = dt.date.fromisoformat(options['from_date'])
            d1 = dt.date.fromisoformat(options['to_date'])
        except ValueError as exc:
            raise CommandError('Invalid --from-date or --to-date (use YYYY-MM-DD).') from exc
        if d0 > d1:
            raise CommandError('--from-date must be on or before --to-date')

        start, _ = _local_day_bounds(d0)
        _, end = _local_day_bounds(d1)

        enc_qs = Encounter.objects.filter(started_at__gte=start, started_at__lte=end).order_by('id')
        patient_ids = set(enc_qs.values_list('patient_id', flat=True))
        patients = {p.id: p for p in Patient.objects.filter(id__in=patient_ids)}

        out_path = options['output']
        with open(out_path, 'w', encoding='utf-8') as out:
            for pid in sorted(patients.keys()):
                out.write(json.dumps(_patient_fhir(patients[pid]), ensure_ascii=False) + '\n')
            for e in enc_qs.iterator():
                out.write(json.dumps(_encounter_fhir(e), ensure_ascii=False) + '\n')

        self.stdout.write(self.style.SUCCESS(f'Wrote {out_path}'))
