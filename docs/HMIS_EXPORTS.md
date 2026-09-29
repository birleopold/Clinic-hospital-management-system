# HMIS-oriented exports

These CSVs support **monthly facility reporting** and reconciliation with national HMIS workflows. They are **not** a full MoH form submission: map columns to your pilot site’s registers and adapt codes to the current MoH condition / service lists.

## Commands

| Command | Purpose |
|---------|---------|
| `python manage.py export_operational_csv [--days N] [-o file.csv]` | Daily facility-wide counts (starter dashboard feed). |
| `python manage.py export_hmis_monthly --year YYYY --month MM --output-dir DIR [--force]` | **C1/C2** bundle: registrations, OPD visits, diagnoses, revenue by service code, diagnosis mix. |
| `python manage.py export_fhir_ndjson --from-date YYYY-MM-DD --to-date YYYY-MM-DD -o file.ndjson` | **D3** minimal FHIR R4 Patient + Encounter NDJSON for pilots. |

All date windows use Django’s **active timezone** (`Africa/Kampala` in `settings`).

## Monthly bundle files (`export_hmis_monthly`)

Files are named with the period suffix `YYYY-MM`.

### `01_new_patients_YYYY-MM.csv`

Patients whose `created_at` falls in the month.

| Column | Description |
|--------|-------------|
| `patient_id` | Internal PK |
| `created_at` | Registration timestamp (ISO) |
| `facility_id` | Facility FK if set |
| `first_name`, `last_name`, `gender`, `date_of_birth`, `phone` | Demographics |
| `consent_data_processing` | 0/1 |

### `02_opd_visits_YYYY-MM.csv`

Encounters with `started_at` in the month (used as **OPD visit** proxy).

| Column | Description |
|--------|-------------|
| `encounter_id` | Internal PK |
| `patient_id` | Link to patient |
| `facility_id`, `facility_name` | Visit site |
| `clinician_id` | Clinician if set |
| `started_at`, `ended_at` | Visit window |
| `status` | `open` / `closed` |
| `chief_complaint` | Free text |

### `03_diagnoses_YYYY-MM.csv`

Diagnoses whose parent encounter started in the month.

| Column | Description |
|--------|-------------|
| `coding_system` | `ICD10`, `WHO_MOH`, or `LOCAL` (see Phase C3) |
| `code`, `description`, `is_primary` | Clinical coding |
| `encounter_started_at` | For register alignment |

### `04_revenue_by_service_code_YYYY-MM.csv`

Aggregates **invoice lines** on invoices **created** in the month (`Invoice.created_at`), grouped by `InvoiceLine.code` (service / tariff code).

| Column | Description |
|--------|-------------|
| `service_code` | Line `code` |
| `line_count` | Number of lines |
| `quantity_sum` | Sum of quantities |
| `line_total_sum` | Sum of `line_total` |

### `05_diagnosis_mix_YYYY-MM.csv`

Counts by `coding_system` + `code` for the same encounter window as file 03 (epidemiological mix).

## Phase C3 — Coding systems

`Diagnosis.coding_system` distinguishes **ICD-10**, **WHO / MoH** style codes used on HMIS condition lists, and **local** clinic codes. Enter the code list your facility actually uses; the export preserves the system for downstream mapping.

## FHIR NDJSON (`export_fhir_ndjson`)

- One JSON object per line: first all **Patient** resources referenced by the encounter set, then each **Encounter**.
- Minimal fields only; suitable for integration spikes, not full clinical fidelity.
- **Privacy**: scrub or restrict use in production according to your DPPA / clinic policy.
