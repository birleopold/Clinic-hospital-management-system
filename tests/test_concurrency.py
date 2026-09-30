"""PostgreSQL-only contention tests; SQLite must not pretend to exercise row locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import pytest
from django.db import connection, close_old_connections
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.accounts.models import User, Facility
from apps.demographics.models import Patient
from apps.operations.models import StockLocation
from apps.inventory.models import InventoryItem, Batch
from apps.pharmacy.models import Dispense
from apps.appointments.models import Appointment

pytestmark = pytest.mark.django_db(transaction=True)


def run_two(fn):
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                fn()
                return "created"
            except ValidationError:
                return "rejected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        return [f.result(timeout=20) for f in futures]


def test_postgres_last_unit_is_not_double_dispensed():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    facility = Facility.objects.create(name="Concurrency")
    patient = Patient.objects.create(
        first_name="Test", last_name="Patient", gender="F", facility=facility
    )
    location = StockLocation.objects.create(facility=facility, name="Pharmacy")
    item = InventoryItem.objects.create(code="LAST", name="Last unit")
    batch = Batch.objects.create(item=item, location=location, quantity_on_hand=1)
    outcomes = run_two(
        lambda: Dispense.objects.create(
            patient_id=patient.pk, batch_id=batch.pk, item_code="LAST", quantity=1
        )
    )
    assert sorted(outcomes) == ["created", "rejected"]
    batch.refresh_from_db()
    assert batch.quantity_on_hand == 0


def test_postgres_appointment_slot_is_not_double_booked():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    patient = Patient.objects.create(first_name="Test", last_name="Patient", gender="F")
    clinician = User.objects.create_user(username="concurrent-doctor", role="clinician")
    starts = timezone.now() + timedelta(days=1)
    outcomes = run_two(
        lambda: Appointment.objects.create(
            patient_id=patient.pk, clinician_id=clinician.pk, scheduled_for=starts
        )
    )
    assert sorted(outcomes) == ["created", "rejected"]


def test_postgres_theatre_room_is_not_double_booked():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    from apps.accounts.models import StaffProfile
    from apps.operations.models import TheatreCase, ServiceRoom
    from apps.operations.specialty_services import create_specialty

    facility = Facility.objects.create(name="Theatre contention")
    actor = User.objects.create_user(username="theatre-admin", role="admin")
    surgeon = User.objects.create_user(username="theatre-doctor", role="clinician")
    for user in (actor, surgeon):
        StaffProfile.objects.update_or_create(
            user=user, defaults={"facility": facility}
        )
    patient = Patient.objects.create(
        first_name="Test", last_name="Patient", gender="F", facility=facility
    )
    room = ServiceRoom.objects.create(facility=facility, name="Theatre")
    starts = timezone.now() + timedelta(days=1)
    outcomes = run_two(
        lambda: create_specialty(
            TheatreCase(
                patient_id=patient.pk,
                room_id=room.pk,
                surgeon_id=surgeon.pk,
                procedure="Test",
                indication="Test",
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
            ),
            actor,
        )
    )
    assert sorted(outcomes) == ["created", "rejected"]
    assert TheatreCase.objects.count() == 1


def test_postgres_offline_retry_creates_one_record():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    import uuid
    import json
    from django.test import Client
    from apps.accounts.models import StaffProfile
    from apps.operations.models import ClinicalEntry, OfflineReceipt

    facility = Facility.objects.create(name="Offline contention")
    actor = User.objects.create_user(username="offline-clinician", role="clinician")
    StaffProfile.objects.update_or_create(user=actor, defaults={"facility": facility})
    patient = Patient.objects.create(
        first_name="Synthetic", last_name="Offline", gender="O", facility=facility
    )
    client = Client()
    client.force_login(actor)

    def post(c, path, data):
        return c.post(
            "/offline/api/" + path,
            data=json.dumps(data),
            content_type="application/json",
        )

    device = post(client, "devices/", {"label": "Concurrency device"}).json()[
        "device_id"
    ]
    pack = post(
        client, "prepare/", {"device_id": device, "patient_ids": [patient.pk]}
    ).json()
    schema = next(s for s in pack["schemas"] if s["slug"] == "clinical")
    proof = next(f for f in schema["fields"] if f["name"] == "patient")["choices"][0][
        "proof"
    ]
    payload = {
        "device_id": device,
        "client_id": str(uuid.uuid4()),
        "client_created_at": timezone.now().isoformat(),
        "slug": "clinical",
        "grant": pack["grant"],
        "values": {
            "patient": str(patient.pk),
            "kind": "note",
            "text": "Concurrent draft",
            "supersedes": "",
        },
        "proofs": {"patient": proof},
    }
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            c = Client()
            c.force_login(actor)
            barrier.wait(timeout=10)
            return post(c, "sync/", payload).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [pool.submit(submit) for _ in range(2)]
        assert sorted(f.result(timeout=30) for f in responses) == [200, 201]
    assert ClinicalEntry.objects.count() == 1 and OfflineReceipt.objects.count() == 1
