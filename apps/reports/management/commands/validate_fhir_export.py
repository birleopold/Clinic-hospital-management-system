import json
import subprocess
import tempfile
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate exported resources with the official HL7 FHIR validator JAR and an explicitly supplied implementation guide."

    def add_arguments(self, parser):
        parser.add_argument("ndjson")
        parser.add_argument("--validator-jar", required=True)
        parser.add_argument("--implementation-guide", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        jar = Path(options["validator_jar"]).resolve()
        if not jar.is_file():
            raise CommandError("Provide the official HL7 validator JAR.")
        source = Path(options["ndjson"])
        resources = []
        try:
            for line in source.read_text().splitlines():
                if line.strip():
                    resources.append(json.loads(line))
        except (OSError, ValueError) as exc:
            raise CommandError("Invalid NDJSON input") from exc
        if not resources:
            raise CommandError("No resources to validate.")
        ids = {(r.get("resourceType"), r.get("id")) for r in resources}
        for resource in resources:
            if resource.get("resourceType") == "Encounter":
                reference = resource.get("subject", {}).get("reference", "").split("/")
                if tuple(reference) not in ids:
                    raise CommandError("Encounter has a missing Patient reference.")
        with tempfile.TemporaryDirectory() as temp:
            bundle = {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [{"resource": r} for r in resources],
            }
            path = Path(temp) / "bundle.json"
            path.write_text(json.dumps(bundle))
            try:
                result = subprocess.run(
                    [
                        "java",
                        "-jar",
                        str(jar),
                        str(path),
                        "-version",
                        "4.0.1",
                        "-ig",
                        options["implementation_guide"],
                        "-output",
                        options["output"],
                    ],
                    check=False,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise CommandError("FHIR validator could not complete.") from exc
            if result.returncode:
                raise CommandError(
                    "FHIR validation failed. Review the OperationOutcome output."
                )
        self.stdout.write(
            "Validator completed. Review warnings and non-computable clinical/reporting requirements separately."
        )
