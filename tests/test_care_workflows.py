from datetime import timedelta
from decimal import Decimal
import hashlib
import io
import json
import sqlite3
import tarfile
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from apps.accounts.models import User, StaffProfile, Facility
from apps.demographics.models import Patient
from apps.inventory.models import StockMovement
from apps.operations.models import (
    Vaccination,
    VaccinationCorrection,
    StorageProtocol,
    ColdChainReading,
    InstrumentCount,
    PerioperativeEntry,
    Delivery,
    Newborn,
    LabourObservation,
)
from apps.operations.care_services import create_care_record, review_care_record
from apps.operations.specialty_services import create_specialty, transition_specialty
from tests.test_suite import suite
from tests.test_specialties import doctor, pregnancy, theatre, vaccine_data

pytestmark = pytest.mark.django_db


def reviewer(suite, role="clinician"):
    user = User.objects.create_user(username="reviewer-" + role, role=role)
    StaffProfile.objects.update_or_create(user=user, defaults={"facility": suite.f})
    return user


def given_vaccine(suite, stock=False):
    suite.b.batch_no = "LOT1"
    suite.b.save()
    record = create_specialty(
        Vaccination(
            patient=suite.p,
            vaccine="Test vaccine",
            dose_label="1",
            due_on=timezone.localdate(),
            stock_source="clinic" if stock else "external",
            stock_batch=suite.b if stock else None,
            stock_quantity=Decimal("1") if stock else None,
        ),
        suite.u,
    )
    data = vaccine_data()
    if stock:
        data["expires_on"] = str(suite.b.expiry)
    transition_specialty(Vaccination, record.pk, "given", data, suite.u)
    record.refresh_from_db()
    return record


def test_vaccine_stock_is_atomic_and_not_repeated(suite):
    record = given_vaccine(suite, True)
    suite.b.refresh_from_db()
    assert suite.b.quantity_on_hand == 9
    assert StockMovement.objects.filter(ref=f"vaccination:{record.pk}").count() == 1
    with pytest.raises(ValidationError):
        transition_specialty(Vaccination, record.pk, "given", vaccine_data(), suite.u)
    suite.b.refresh_from_db()
    assert suite.b.quantity_on_hand == 9


def test_quarantined_vaccine_has_no_partial_administration(suite):
    suite.b.quarantined = True
    suite.b.save()
    with pytest.raises(ValidationError):
        given_vaccine(suite, True)
    suite.b.refresh_from_db()
    assert (
        suite.b.quantity_on_hand == 10
        and not Vaccination.objects.filter(status="given").exists()
    )
    assert not StockMovement.objects.exists()


def test_vaccination_correction_needs_second_reviewer_and_preserves_stock(suite):
    record = given_vaccine(suite, True)
    correction = create_care_record(
        VaccinationCorrection(
            vaccination=record,
            field_name="site",
            corrected_value="Corrected site",
            reason="Transcription error",
        ),
        suite.u,
    )
    with pytest.raises(ValidationError):
        review_care_record(VaccinationCorrection, correction.pk, "approve", {}, suite.u)
    doctor = reviewer(suite)
    review_care_record(VaccinationCorrection, correction.pk, "approve", {}, doctor)
    review_care_record(VaccinationCorrection, correction.pk, "approve", {}, doctor)
    record.refresh_from_db()
    suite.b.refresh_from_db()
    assert record.site == "Corrected site" and suite.b.quantity_on_hand == 9
    assert record.history.filter(site="Recorded site").exists()
    correction.refresh_from_db()
    assert correction.original_value == "Recorded site"


def test_stale_correction_cannot_overwrite_newer_review(suite):
    record = given_vaccine(suite)
    drafts = [
        create_care_record(
            VaccinationCorrection(
                vaccination=record,
                field_name="site",
                corrected_value=value,
                reason="Review",
            ),
            suite.u,
        )
        for value in ("Site A", "Site B")
    ]
    doctor = reviewer(suite)
    review_care_record(VaccinationCorrection, drafts[0].pk, "approve", {}, doctor)
    with pytest.raises(ValidationError):
        review_care_record(VaccinationCorrection, drafts[1].pk, "approve", {}, doctor)


def test_storage_protocol_review_and_excursion_quarantine(suite):
    protocol = create_care_record(
        StorageProtocol(
            facility=suite.f,
            name="Synthetic test protocol",
            lower_c=2,
            upper_c=8,
            source_reference="Test only; not a clinical default",
        ),
        suite.u,
    )
    reading = lambda: ColdChainReading(
        batch=suite.b,
        protocol=protocol,
        measured_at=timezone.now(),
        temperature_c=10,
        device_reference="Test sensor",
    )
    with pytest.raises(ValidationError):
        create_care_record(reading(), suite.u)
    boss = reviewer(suite, "manager")
    review_care_record(StorageProtocol, protocol.pk, "approve", {}, boss)
    result = create_care_record(reading(), suite.u)
    suite.b.refresh_from_db()
    assert result.excursion and suite.b.quarantined
    create_care_record(
        ColdChainReading(
            batch=suite.b,
            protocol=protocol,
            measured_at=timezone.now(),
            temperature_c=4,
            device_reference="Test sensor",
        ),
        suite.u,
    )
    suite.b.refresh_from_db()
    assert suite.b.quarantined  # no automatic release


def test_theatre_count_verification_blocks_completion(suite, doctor):
    case = theatre(suite, doctor)
    for action, data in [
        ("ready", {"consent_reference": "Consent", "checklist_reference": "Checklist"}),
        ("in_progress", {}),
        ("recovery", {"note": "Recovery handoff"}),
    ]:
        transition_specialty(type(case), case.pk, action, data, suite.u)
    count = create_care_record(
        InstrumentCount(
            case=case,
            phase="closure",
            item_group="Synthetic instruments",
            expected=5,
            counted=4,
            discrepancy_note="One item awaiting reconciliation",
        ),
        suite.u,
    )
    with pytest.raises(ValidationError):
        transition_specialty(
            type(case), case.pk, "completed", {"note": "Handoff"}, suite.u
        )
    with pytest.raises(ValidationError):
        review_care_record(InstrumentCount, count.pk, "approve", {}, doctor)
    review_care_record(
        InstrumentCount,
        count.pk,
        "approve",
        {"resolution": "Clinical team documented reconciliation reference COUNT1"},
        doctor,
    )
    transition_specialty(type(case), case.pk, "completed", {"note": "Handoff"}, suite.u)
    case.refresh_from_db()
    assert case.status == "completed"


def test_delivery_and_newborn_link_enforce_identity_and_birth_date(suite):
    episode = pregnancy(suite)
    delivery = create_care_record(
        Delivery(
            pregnancy=episode,
            occurred_at=timezone.now(),
            mode="Recorded method",
            maternal_condition="Recorded",
            complications="Reviewed absence",
            care_provided="Recorded care",
            follow_up_plan="Recorded plan",
        ),
        suite.u,
    )
    wrong = Newborn(
        delivery=delivery,
        patient=suite.p,
        birth_order=1,
        outcome="live_birth",
        notes="Test",
    )
    with pytest.raises(ValidationError):
        create_care_record(wrong, suite.u)
    baby = Patient.objects.create(
        first_name="Synthetic",
        last_name="Infant",
        gender="F",
        facility=suite.f,
        date_of_birth=timezone.localdate(),
    )
    newborn = create_care_record(
        Newborn(
            delivery=delivery,
            patient=baby,
            birth_order=1,
            outcome="live_birth",
            birth_weight_kg=Decimal("3.200"),
            apgar_1_min=8,
            apgar_5_min=9,
            notes="Synthetic observation",
        ),
        suite.u,
    )
    assert (
        newborn.delivery.pregnancy.patient_id == suite.p.pk
        and newborn.patient_id == baby.pk
    )
    with pytest.raises(ValidationError):
        create_care_record(
            Newborn(
                delivery=delivery,
                birth_order=2,
                outcome="live_birth",
                notes="No registered identity",
            ),
            suite.u,
        )


def test_labour_observation_correction_and_future_validation(suite):
    episode = pregnancy(suite)
    observation = create_care_record(
        LabourObservation(
            pregnancy=episode,
            observed_at=timezone.now(),
            cervical_dilation_cm=4,
            findings="Recorded observation",
            plan="Clinician plan",
        ),
        suite.u,
    )
    with pytest.raises(ValidationError):
        create_care_record(
            LabourObservation(
                pregnancy=episode,
                observed_at=timezone.now() + timedelta(days=1),
                findings="Future",
                plan="Plan",
            ),
            suite.u,
        )
    correction = create_care_record(
        LabourObservation(
            pregnancy=episode,
            observed_at=observation.observed_at,
            cervical_dilation_cm=3,
            findings="Corrected",
            plan="Plan",
            supersedes=observation,
            amendment_reason="Transcription",
        ),
        suite.u,
    )
    observation.refresh_from_db()
    assert (
        observation.cervical_dilation_cm == 4 and correction.cervical_dilation_cm == 3
    )


def bundle(tmp_path, malicious=False):
    source = tmp_path / "bundle"
    source.mkdir()
    with sqlite3.connect(source / "database.sqlite3") as db:
        db.execute("CREATE TABLE demographics_patient (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO demographics_patient VALUES (1)")
    with tarfile.open(source / "media.tar.gz", "w:gz") as tar:
        member = tarfile.TarInfo("../escape" if malicious else "media/synthetic.txt")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"test"))
    manifest = {"engine": "django.db.backends.sqlite3", "files": {}}
    for name in ("database.sqlite3", "media.tar.gz"):
        manifest["files"][name] = hashlib.sha256(
            (source / name).read_bytes()
        ).hexdigest()
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source


def test_isolated_restore_checks_hashes_and_media(tmp_path):
    source = bundle(tmp_path)
    target = tmp_path / "restored"
    call_command("verify_backup_bundle", str(source), str(target), stdout=io.StringIO())
    report = json.loads((target / "restore-report.json").read_text())
    assert (
        report["row_counts"]["demographics_patient"] == 1
        and (target / "media/synthetic.txt").read_text() == "test"
    )
    with pytest.raises(CommandError):
        call_command("verify_backup_bundle", str(source), str(target))
    (source / "database.sqlite3").write_bytes(b"tampered")
    with pytest.raises(CommandError):
        call_command("verify_backup_bundle", str(source), str(tmp_path / "invalid"))


def test_restore_rejects_archive_traversal_before_writing(tmp_path):
    source = bundle(tmp_path, True)
    with pytest.raises(CommandError):
        call_command("verify_backup_bundle", str(source), str(tmp_path / "target"))
    assert not (tmp_path / "target").exists() and not (tmp_path / "escape").exists()


def test_adverse_event_requires_given_dose_and_clinical_follow_up(suite):
    from apps.operations.models import VaccinationAdverseEvent

    record = given_vaccine(suite)
    event = create_care_record(
        VaccinationAdverseEvent(
            vaccination=record,
            occurred_at=timezone.now(),
            description="Synthetic suspected event",
            action_taken="Staff action documented",
        ),
        suite.u,
    )
    clinician = reviewer(suite)
    review_care_record(
        VaccinationAdverseEvent,
        event.pk,
        "approve",
        {"assessment": "Clinician reviewed; follow-up arranged"},
        clinician,
    )
    review_care_record(
        VaccinationAdverseEvent,
        event.pk,
        "close",
        {"assessment": "Follow-up documented"},
        clinician,
    )
    event.refresh_from_db()
    assert (
        event.status == "closed" and event.reviewed_by == clinician and event.closed_at
    )
    with pytest.raises(ValidationError):
        review_care_record(
            VaccinationAdverseEvent,
            event.pk,
            "close",
            {"assessment": "Duplicate"},
            clinician,
        )


def test_review_ui_enforces_two_people_and_facility_access(suite):
    from django.urls import reverse

    record = given_vaccine(suite)
    response = suite.client.post(
        "/suite/vaccination-corrections/",
        {
            "vaccination": record.pk,
            "field_name": "site",
            "corrected_value": "Reviewed site",
            "reason": "Transcription correction",
        },
    )
    assert response.status_code == 302
    correction = VaccinationCorrection.objects.get()
    url = reverse(
        "suite-action", args=["vaccination-corrections", correction.pk, "approve"]
    )
    suite.client.post(url)
    correction.refresh_from_db()
    assert correction.applied_at is None
    clinician = reviewer(suite)
    suite.client.force_login(clinician)
    assert suite.client.post(url).status_code == 302
    correction.refresh_from_db()
    assert correction.applied_at and correction.approved_by == clinician
    other = Facility.objects.create(name="Separate clinic")
    StaffProfile.objects.filter(user=clinician).update(facility=other)
    assert suite.client.post(url).status_code == 404
