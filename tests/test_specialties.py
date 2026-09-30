from datetime import timedelta
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Facility, StaffProfile
from apps.demographics.models import Patient
from apps.appointments.models import Appointment
from apps.operations.models import (
    TheatreCase,
    Pregnancy,
    MaternityVisit,
    Vaccination,
    RehabilitationPlan,
    RehabilitationSession,
    ServiceRoom,
)
from apps.operations.specialty_services import create_specialty, transition_specialty
from tests.test_suite import suite

pytestmark = pytest.mark.django_db


@pytest.fixture
def doctor(suite):
    user = User.objects.create_user(username="specialist", role="clinician")
    StaffProfile.objects.update_or_create(user=user, defaults={"facility": suite.f})
    return user


def theatre(suite, doctor, **kw):
    starts = timezone.now() + timedelta(hours=2)
    data = dict(
        patient=suite.p,
        room=ServiceRoom.objects.create(facility=suite.f, name="Theatre"),
        surgeon=doctor,
        procedure="Test procedure",
        indication="Test indication",
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
    )
    data.update(kw)
    return create_specialty(TheatreCase(**data), suite.u)


def pregnancy(suite):
    return create_specialty(
        Pregnancy(
            patient=suite.p,
            gravida=1,
            parity=0,
            estimated_due_date=timezone.localdate() + timedelta(days=100),
            assessment="Clinician assessment",
        ),
        suite.u,
    )


def transition(obj, op, suite, **data):
    return transition_specialty(type(obj), obj.pk, op, data, suite.u)


def test_theatre_handoffs_require_evidence_and_preserve_history(suite, doctor):
    case = theatre(suite, doctor)
    with pytest.raises(ValidationError):
        transition(case, "in_progress", suite)
    with pytest.raises(ValidationError):
        transition(case, "ready", suite, consent_reference="Consent")
    transition(
        case,
        "ready",
        suite,
        consent_reference="Consent123",
        checklist_reference="Checklist123",
    )
    transition(case, "in_progress", suite)
    with pytest.raises(ValidationError):
        transition(case, "completed", suite, note="Too early")
    transition(case, "recovery", suite, note="Procedure outcome")
    transition(case, "completed", suite, note="Ward handoff")
    case.refresh_from_db()
    assert case.status == "completed" and case.started_at and case.completed_at
    assert case.history.count() == 5 and "Ward handoff" in case.outcome_note
    with pytest.raises(ValidationError):
        transition(case, "cancelled", suite, note="Finalized")


def test_theatre_and_appointments_share_resource_conflicts(suite, doctor):
    case = theatre(suite, doctor)
    with pytest.raises(ValidationError):
        create_specialty(
            TheatreCase(
                patient=suite.p,
                room=case.room,
                surgeon=doctor,
                procedure="Conflict",
                indication="Test",
                starts_at=case.starts_at,
                ends_at=case.ends_at,
            ),
            suite.u,
        )
    with pytest.raises(ValidationError):
        Appointment.objects.create(
            patient=suite.p,
            clinician=doctor,
            room=case.room,
            scheduled_for=case.starts_at,
        )
    transition(case, "cancelled", suite, note="Rescheduled")
    Appointment.objects.create(
        patient=suite.p, clinician=doctor, room=case.room, scheduled_for=case.starts_at
    )
    with pytest.raises(ValidationError):
        create_specialty(
            TheatreCase(
                patient=suite.p,
                room=case.room,
                surgeon=doctor,
                procedure="Conflict",
                indication="Test",
                starts_at=case.starts_at,
                ends_at=case.ends_at,
            ),
            suite.u,
        )


def test_theatre_start_refuses_overrun_of_previous_case(suite, doctor):
    first = theatre(suite, doctor)
    second = create_specialty(
        TheatreCase(
            patient=suite.p,
            room=first.room,
            surgeon=doctor,
            procedure="Next",
            indication="Test",
            starts_at=first.ends_at,
            ends_at=first.ends_at + timedelta(hours=1),
        ),
        suite.u,
    )
    for case in (first, second):
        transition(
            case,
            "ready",
            suite,
            consent_reference="Consent",
            checklist_reference="Checklist",
        )
    transition(first, "in_progress", suite)
    with pytest.raises(ValidationError):
        transition(second, "in_progress", suite)


def test_pregnancy_episode_and_append_only_amendment(suite):
    episode = pregnancy(suite)
    with pytest.raises(ValidationError):
        pregnancy(suite)
    visit = create_specialty(
        MaternityVisit(
            pregnancy=episode,
            occurred_at=timezone.now(),
            visit_type="antenatal",
            findings="Original",
            care_provided="Care",
            plan="Plan",
        ),
        suite.u,
    )
    correction = create_specialty(
        MaternityVisit(
            pregnancy=episode,
            occurred_at=visit.occurred_at,
            visit_type="antenatal",
            findings="Corrected",
            care_provided="Care",
            plan="Plan",
            supersedes=visit,
            amendment_reason="Transcription correction",
        ),
        suite.u,
    )
    visit.refresh_from_db()
    assert visit.findings == "Original" and correction.supersedes_id == visit.pk
    transition(
        episode, "close", suite, outcome="Documented outcome", note="Follow-up arranged"
    )
    with pytest.raises(ValidationError):
        create_specialty(
            MaternityVisit(
                pregnancy=episode,
                occurred_at=timezone.now(),
                visit_type="antenatal",
                findings="Test",
                care_provided="Care",
                plan="Plan",
            ),
            suite.u,
        )
    create_specialty(
        MaternityVisit(
            pregnancy=episode,
            occurred_at=timezone.now(),
            visit_type="postnatal",
            findings="Test",
            care_provided="Care",
            plan="Plan",
        ),
        suite.u,
    )


def vaccine_data():
    return dict(
        administered_at=(timezone.now() - timedelta(minutes=5)).isoformat(),
        manufacturer="Test manufacturer",
        lot_number="LOT1",
        expires_on=str(timezone.localdate() + timedelta(days=30)),
        dose="Recorded dose",
        route="Recorded route",
        site="Recorded site",
        consent_reference="Consent record",
    )


def test_vaccination_records_actual_dose_once_and_rejects_expiry(suite):
    record = create_specialty(
        Vaccination(
            patient=suite.p,
            vaccine="Test vaccine",
            dose_label="Dose 1",
            due_on=timezone.localdate(),
        ),
        suite.u,
    )
    data = vaccine_data()
    with pytest.raises(ValidationError):
        transition(
            record,
            "given",
            suite,
            **{**data, "expires_on": str(timezone.localdate() - timedelta(days=1))}
        )
    with pytest.raises(ValidationError):
        transition(
            record,
            "given",
            suite,
            **{
                **data,
                "administered_at": (timezone.now() + timedelta(days=1)).isoformat(),
            }
        )
    transition(record, "deferred", suite, note="Patient requested another date")
    transition(
        record,
        "scheduled",
        suite,
        note="Confirmed return",
        due_on=str(timezone.localdate()),
    )
    transition(record, "given", suite, **data)
    record.refresh_from_db()
    assert (
        record.status == "given"
        and record.administered_by_id == suite.u.pk
        and record.lot_number == "LOT1"
    )
    with pytest.raises(ValidationError):
        transition(record, "given", suite, **data)


def test_rehabilitation_closed_plan_rejects_new_sessions(suite, doctor):
    plan = create_specialty(
        RehabilitationPlan(
            patient=suite.p,
            clinician=doctor,
            problem="Mobility",
            baseline="Recorded baseline",
            goals="Patient goal",
            intervention_plan="Clinician plan",
            review_on=timezone.localdate(),
        ),
        suite.u,
    )
    data = dict(
        plan=plan,
        occurred_at=timezone.now(),
        intervention="Session",
        response="Observed",
        progress="Recorded",
    )
    session = create_specialty(RehabilitationSession(**data), suite.u)
    transition(plan, "completed", suite, note="Goals reviewed; discharge plan recorded")
    with pytest.raises(ValidationError):
        create_specialty(RehabilitationSession(**data), suite.u)
    amended = create_specialty(
        RehabilitationSession(
            **{**data, "progress": "Corrected"},
            supersedes=session,
            amendment_reason="Correction"
        ),
        suite.u,
    )
    assert amended.supersedes_id == session.pk


def test_specialty_scope_and_role_denials(suite, doctor):
    other = Facility.objects.create(name="Other facility")
    patient = Patient.objects.create(
        first_name="Other", last_name="Patient", gender="F", facility=other
    )
    with pytest.raises(PermissionDenied):
        create_specialty(
            Vaccination(
                patient=patient,
                vaccine="Test",
                dose_label="1",
                due_on=timezone.localdate(),
            ),
            suite.u,
        )
    foreign = Vaccination.objects.create(
        patient=patient,
        vaccine="Foreign",
        dose_label="1",
        due_on=timezone.localdate(),
        created_by=suite.u,
    )
    assert (
        suite.client.post(
            reverse("suite-action", args=["vaccinations", foreign.pk, "cancelled"]),
            {"note": "Attempt"},
        ).status_code
        == 404
    )
    suite.u.role = "cashier"
    suite.u.save()
    assert suite.client.get("/suite/pregnancies/").status_code == 403
    assert (
        suite.client.post("/suite/vaccinations/", {"patient": suite.p.pk}).status_code
        == 403
    )


def test_specialty_forms_save_valid_records_and_display_errors(suite):
    response = suite.client.post(
        "/suite/vaccinations/",
        {
            "patient": suite.p.pk,
            "vaccine": "Synthetic vaccine",
            "dose_label": "Dose 1",
            "due_on": str(timezone.localdate()),
        },
    )
    assert response.status_code == 302 and Vaccination.objects.count() == 1
    record = Vaccination.objects.get()
    response = suite.client.post(
        reverse("suite-action", args=["vaccinations", record.pk, "given"]),
        vaccine_data(),
    )
    assert response.status_code == 302
    record.refresh_from_db()
    assert record.status == "given"
    response = suite.client.post(
        "/suite/pregnancies/",
        {
            "patient": suite.p.pk,
            "gravida": 1,
            "parity": 2,
            "estimated_due_date": str(timezone.localdate()),
            "assessment": "Test",
        },
    )
    assert response.status_code == 200 and not Pregnancy.objects.exists()


def test_follow_up_uses_latest_visit_and_hides_other_facilities(suite):
    episode = pregnancy(suite)
    for days_ago, followup in [
        (2, timezone.localdate() - timedelta(days=1)),
        (1, timezone.localdate() + timedelta(days=7)),
    ]:
        create_specialty(
            MaternityVisit(
                pregnancy=episode,
                occurred_at=timezone.now() - timedelta(days=days_ago),
                visit_type="antenatal",
                findings="Test",
                care_provided="Care",
                plan="Plan",
                follow_up_on=followup,
            ),
            suite.u,
        )
    create_specialty(
        Vaccination(
            patient=suite.p,
            vaccine="Due vaccine",
            dose_label="1",
            due_on=timezone.localdate(),
        ),
        suite.u,
    )
    response = suite.client.get("/suite/specialty-follow-up/")
    assert response.status_code == 200
    groups = response.context["groups"]
    assert groups[0]["count"] == 1 and groups[1]["count"] == 0
    assert (
        suite.client.get(
            "/suite/vaccinations/",
            {"q": str(suite.p.medical_record_id), "status": "scheduled"},
        )
        .context["page"]
        .paginator.count
        == 1
    )
    assert (
        suite.client.get(
            "/suite/vaccinations/", {"q": suite.p.first_name, "status": "given"}
        )
        .context["page"]
        .paginator.count
        == 0
    )


def test_amendment_cannot_cross_maternity_episodes(suite):
    episode = pregnancy(suite)
    original = create_specialty(
        MaternityVisit(
            pregnancy=episode,
            occurred_at=timezone.now(),
            visit_type="antenatal",
            findings="Original",
            care_provided="Care",
            plan="Plan",
        ),
        suite.u,
    )
    transition(episode, "close", suite, outcome="Outcome", note="Closure")
    new = pregnancy(suite)
    with pytest.raises(ValidationError):
        create_specialty(
            MaternityVisit(
                pregnancy=new,
                occurred_at=timezone.now(),
                visit_type="antenatal",
                findings="Wrong episode",
                care_provided="Care",
                plan="Plan",
                supersedes=original,
                amendment_reason="Wrong",
            ),
            suite.u,
        )


def test_visit_action_is_rejected_without_server_error(suite):
    episode = pregnancy(suite)
    visit = create_specialty(
        MaternityVisit(
            pregnancy=episode,
            occurred_at=timezone.now(),
            visit_type="antenatal",
            findings="Test",
            care_provided="Care",
            plan="Plan",
        ),
        suite.u,
    )
    response = suite.client.post(
        reverse("suite-action", args=["maternity-visits", visit.pk, "close"])
    )
    assert response.status_code == 302
    visit.refresh_from_db()
    assert visit.findings == "Test"


def test_full_record_details_preserve_long_notes_and_zero_parity(suite):
    episode = pregnancy(suite)
    long_text = "Full clinical documentation. " * 30
    episode.assessment = long_text
    episode.save()
    response = suite.client.get(
        reverse("suite-specialty-detail", args=["pregnancies", episode.pk])
    )
    assert response.status_code == 200 and long_text.encode() in response.content
    details = response.context["details"]
    assert next(item["value"] for item in details if item["label"] == "parity") == "0"
    response = suite.client.get("/suite/pregnancies/")
    assert "0" in response.context["rows"][0]["values"]
