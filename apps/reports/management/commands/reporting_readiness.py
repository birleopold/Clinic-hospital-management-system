import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from apps.demographics.models import Patient
from apps.encounters.models import Encounter, Diagnosis
from apps.accounts.models import Facility


class Command(BaseCommand):
    help = "Report data-quality gaps against an explicitly supplied, approved HMIS mapping file."

    def add_arguments(self, parser):
        parser.add_argument("--facility-id", type=int, required=True)
        parser.add_argument("--mapping", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        try:
            mapping = json.loads(Path(options["mapping"]).read_text())
        except (OSError, ValueError) as exc:
            raise CommandError("Mapping must be a JSON file.") from exc
        if not all(
            mapping.get(k)
            for k in ("version", "approved_by", "approved_at", "diagnosis_codes")
        ):
            raise CommandError(
                "Mapping requires version, approved_by, approved_at and diagnosis_codes."
            )
        facility = Facility.objects.get(pk=options["facility_id"])
        patients = Patient.objects.filter(facility=facility, merged_into__isnull=True)
        codes = set(mapping["diagnosis_codes"])
        unmapped = [
            c
            for c in Diagnosis.objects.filter(encounter__facility=facility)
            .values_list("code", flat=True)
            .distinct()
            if c not in codes
        ]
        report = {
            "facility": facility.pk,
            "mapping_version": mapping["version"],
            "missing_birth_dates": patients.filter(date_of_birth__isnull=True).count(),
            "missing_facility_code": not bool(facility.code),
            "unmapped_diagnosis_codes": unmapped,
            "is_national_certification": False,
        }
        Path(options["output"]).write_text(json.dumps(report, indent=2))
        if options["strict"] and (
            report["missing_birth_dates"] or report["missing_facility_code"] or unmapped
        ):
            raise CommandError(
                "Reporting data-quality issues found; review the saved report."
            )
        self.stdout.write(
            "Data-quality report saved; indicator reconciliation with the approved register remains required."
        )
