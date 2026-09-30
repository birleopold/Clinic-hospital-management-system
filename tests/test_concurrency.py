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
    from apps.pharmacy.models import MedicineProfile, PharmacyPolicy
    MedicineProfile.objects.create(item=item, reviewed=True, prescription_required=False)
    PharmacyPolicy.objects.create(facility=facility, allow_retail=True)
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


def test_postgres_merge_blocks_late_bulk_patient_write():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from threading import Event
    from concurrent.futures import TimeoutError
    from django.db import transaction, IntegrityError
    from apps.operations.models import ClinicalEntry, DuplicateReview
    from apps.operations.advanced_services import merge_patients
    f=Facility.objects.create(name='Identity contention')
    u=User.objects.create_user(username='merge-concurrency',role='admin',is_superuser=True)
    source=Patient.objects.create(first_name='Source',last_name='Synthetic',gender='F',facility=f)
    target=Patient.objects.create(first_name='Target',last_name='Synthetic',gender='F',facility=f)
    review=DuplicateReview.objects.create(patient=target,candidate=source,status='confirmed',created_by=u)
    entered=Event()
    def write():
        close_old_connections()
        try:
            entered.set()
            ClinicalEntry.objects.bulk_create([ClinicalEntry(patient_id=source.pk,created_by_id=u.pk,kind='note',text='Late write')])
            return 'created'
        except IntegrityError:return 'rejected'
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Patient.objects.select_for_update().get(pk=source.pk)
            future=pool.submit(write)
            assert entered.wait(timeout=5)
            with pytest.raises(TimeoutError):future.result(timeout=.2)
            merge_patients(review.pk,u,'Verified synthetic identity')
        assert future.result(timeout=10)=='rejected'
    assert not ClinicalEntry.objects.filter(patient=source).exists()


@pytest.mark.parametrize('same_basket',[True,False])
def test_postgres_basket_checkout_replay_and_final_unit(same_basket):
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from apps.accounts.models import StaffProfile
    from apps.billing.models import PriceList, PriceListItem, Invoice
    from apps.pharmacy.models import MedicineProfile, Prescription, PrescriptionItem, BasketAllocation
    from apps.pharmacy.checkout_services import create_basket, add_item, checkout
    facility=Facility.objects.create(name='Basket contention')
    actor=User.objects.create_user(username='basket-dispenser',role='pharmacy')
    StaffProfile.objects.update_or_create(user=actor,defaults={'facility':facility})
    item=InventoryItem.objects.create(code='BASKET-LAST',name='Synthetic last unit')
    MedicineProfile.objects.create(item=item,reviewed=True)
    price=PriceList.objects.create(name='Synthetic')
    PriceListItem.objects.create(pricelist=price,code=item.code,name=item.name,amount=100)
    batch=Batch.objects.create(item=item,location=StockLocation.objects.create(facility=facility,name='Shelf'),quantity_on_hand=1)
    baskets=[]
    for number in range(1 if same_basket else 2):
        patient=Patient.objects.create(first_name=f'Basket {number}',last_name='Synthetic',gender='F',facility=facility)
        pi=PrescriptionItem.objects.create(prescription=Prescription.objects.create(patient=patient),item_code=item.code,quantity=1)
        basket=create_basket(patient.pk,actor)
        add_item(basket.pk,actor,1,item.code,1,pi.pk)
        baskets.append(basket)
    if same_basket:baskets.append(baskets[0])
    barrier=Barrier(2)
    def run(basket):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return checkout(basket.pk,actor,2,basket.checkout_key).invoice_id
        except ValidationError:return None
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,basket) for basket in baskets]
        results=[f.result(timeout=20) for f in futures]
    if same_basket:assert results[0] and results[0]==results[1]
    else:assert sum(result is not None for result in results)==1
    batch.refresh_from_db();assert batch.quantity_on_hand==0
    assert Dispense.objects.count()==1 and BasketAllocation.objects.count()==1
    assert Invoice.objects.count()==1 and Invoice.objects.get().total_amount==100
