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
