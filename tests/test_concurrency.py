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


def test_postgres_pending_settlements_cannot_overcommit_expense():
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from decimal import Decimal
    from uuid import uuid4
    from apps.accounts.models import StaffProfile
    from apps.operations.models import OperatingBudget, OperatingExpense, ExpenseSettlement
    from apps.operations.settlement_services import record_settlement

    facility = Facility.objects.create(name='Settlement contention')
    actor = User.objects.create_user(username='settlement-manager', role='manager')
    StaffProfile.objects.update_or_create(user=actor, defaults={'facility': facility})
    today = timezone.localdate()
    budget = OperatingBudget.objects.create(facility=facility, cost_centre='Synthetic', starts_on=today,
        ends_on=today + timedelta(days=30), amount=1000, status='approved', created_by=actor)
    expense = OperatingExpense.objects.create(budget=budget, incurred_on=today, payee='Synthetic',
        reference='CONCURRENT', description='Synthetic invoice', amount=800, status='approved', created_by=actor)
    outcomes = run_two(lambda: record_settlement(actor, expense.pk, amount=Decimal('500'),
        paid_on=today, method='bank', account_reference='Synthetic account',
        transaction_reference=str(uuid4()), evidence='Synthetic statement', request_key=uuid4()))
    assert sorted(outcomes) == ['created', 'rejected']
    assert ExpenseSettlement.objects.filter(expense=expense).count() == 1


def test_postgres_settlement_replay_records_one_payment():
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from decimal import Decimal
    from uuid import uuid4
    from apps.accounts.models import StaffProfile
    from apps.operations.models import OperatingBudget, OperatingExpense, ExpenseSettlement
    from apps.operations.settlement_services import record_settlement

    facility = Facility.objects.create(name='Settlement replay')
    actor = User.objects.create_user(username='settlement-replay-manager', role='manager')
    StaffProfile.objects.update_or_create(user=actor, defaults={'facility': facility})
    today = timezone.localdate()
    budget = OperatingBudget.objects.create(facility=facility, cost_centre='Synthetic', starts_on=today,
        ends_on=today + timedelta(days=30), amount=1000, status='approved', created_by=actor)
    expense = OperatingExpense.objects.create(budget=budget, incurred_on=today, payee='Synthetic',
        reference='REPLAY', description='Synthetic invoice', amount=800, status='approved', created_by=actor)
    data = dict(amount=Decimal('500'), paid_on=today, method='bank', account_reference='Synthetic account',
        transaction_reference='SAME-TRANSACTION', evidence='Synthetic statement', request_key=uuid4())
    assert run_two(lambda: record_settlement(actor, expense.pk, **data)) == ['created', 'created']
    assert ExpenseSettlement.objects.filter(expense=expense).count() == 1


def test_postgres_diagnostic_equipment_cannot_be_double_reserved():
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from apps.accounts.models import StaffProfile
    from apps.orders.models import Order
    from apps.operations.models import FacilityAsset, DiagnosticWorkItem
    from apps.operations.diagnostic_services import schedule

    facility = Facility.objects.create(name='Diagnostic resource contention')
    operators = [User.objects.create_user(username=f'diagnostic-operator-{i}', role='radiology') for i in range(2)]
    orders = []
    for i, operator in enumerate(operators):
        StaffProfile.objects.update_or_create(user=operator, defaults={'facility': facility})
        patient = Patient.objects.create(first_name='Synthetic', last_name=f'Patient {i}', gender='F', facility=facility)
        orders.append(Order.objects.create(patient=patient, order_type='imaging', code=f'SYNTHETIC-{i}', description='Synthetic study'))
    asset = FacilityAsset.objects.create(facility=facility, tag='SYNTHETIC-SCANNER', name='Synthetic scanner',
        location='Synthetic room', custodian=operators[0], status='operational', created_by=operators[0])
    starts = timezone.now() + timedelta(days=1)
    barrier = Barrier(2)

    def reserve(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                schedule(orders[index].pk, operators[index], operators[index], 'CT', starts, '', 1, asset=asset)
                return 'created'
            except ValidationError:
                return 'rejected'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result(timeout=20) for future in [pool.submit(reserve, i) for i in range(2)]]
    assert sorted(outcomes) == ['created', 'rejected']
    assert DiagnosticWorkItem.objects.filter(asset=asset).count() == 1


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


@pytest.mark.parametrize('same_key',[True,False])
def test_postgres_cash_collection_retry_and_competing_cashiers(same_key):
    import uuid
    from apps.accounts.models import StaffProfile
    from apps.billing.models import Invoice, Payment
    from apps.billing.payment_services import collect_cash
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    facility=Facility.objects.create(name='Cash contention')
    patient=Patient.objects.create(first_name='Cash',last_name='Synthetic',gender='F',facility=facility)
    invoice=Invoice.objects.create(patient=patient,total_amount=100,status='ready_to_pay')
    actors=[]
    for n in range(1 if same_key else 2):
        actor=User.objects.create_user(username=f'cash-race-{n}',role='cashier')
        StaffProfile.objects.update_or_create(user=actor,defaults={'facility':facility});actors.append(actor)
    if same_key:actors.append(actors[0])
    keys=[uuid.uuid4(),uuid.uuid4()]
    if same_key:keys[1]=keys[0]
    barrier=Barrier(2)
    def run(n):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return collect_cash(invoice.pk,actors[n],100,keys[n])[0].pk
        except ValidationError:return None
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,n) for n in range(2)];results=[f.result(timeout=20) for f in futures]
    if same_key:assert results[0] and results[0]==results[1]
    else:assert sum(r is not None for r in results)==1
    assert Payment.objects.count()==1
    invoice.refresh_from_db();assert invoice.paid_amount==100


def test_postgres_concurrent_returns_cannot_overcredit_or_restock():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from apps.accounts.models import StaffProfile
    from apps.billing.models import Invoice, InvoiceLine
    from apps.pharmacy.models import Prescription, PrescriptionItem
    from apps.operations.finance_services import request_return, review_return
    from apps.operations.models import MedicineReturn
    facility=Facility.objects.create(name='Return contention')
    patient=Patient.objects.create(first_name='Return',last_name='Synthetic',gender='F',facility=facility)
    creator=User.objects.create_user(username='return-pharmacy',role='pharmacy')
    manager=User.objects.create_user(username='return-manager',role='manager')
    for actor in (creator,manager):StaffProfile.objects.update_or_create(user=actor,defaults={'facility':facility})
    item=InventoryItem.objects.create(code='RETURN-RACE',name='Synthetic')
    batch=Batch.objects.create(item=item,location=StockLocation.objects.create(facility=facility,name='Shelf'),quantity_on_hand=1)
    pi=PrescriptionItem.objects.create(prescription=Prescription.objects.create(patient=patient),item_code=item.code,quantity=1)
    disp=Dispense.objects.create(patient=patient,item_code=item.code,prescription_item=pi,batch=batch,quantity=1)
    line=InvoiceLine.objects.get(source_ref=f'dispense:{disp.pk}');line.unit_price=100;line.save()
    Invoice.objects.filter(pk=line.invoice_id).update(total_amount=100)
    requests=[request_return(disp.pk,creator,1,'quarantine','Return','Isolate') for _ in range(2)]
    barrier=Barrier(2)
    def run(obj):
        close_old_connections()
        try:
            barrier.wait(timeout=10);review_return(obj.pk,manager,'post','Checked');return 'posted'
        except ValidationError:return 'rejected'
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,obj) for obj in requests];assert sorted(f.result(timeout=20) for f in futures)==['posted','rejected']
    assert MedicineReturn.objects.filter(status='posted').count()==1
    assert InvoiceLine.objects.filter(source_ref__startswith='return:').count()==1
    assert Invoice.objects.get(pk=line.invoice_id).total_amount==0


def test_postgres_receipts_cannot_exceed_approved_purchase_quantity():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from apps.inventory.models import PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine, Supplier, StockMovement
    from apps.inventory.services import post_goods_receipt
    facility=Facility.objects.create(name='Receiving contention')
    location=StockLocation.objects.create(facility=facility,name='Shelf')
    item=InventoryItem.objects.create(code='RECEIVE-RACE',name='Synthetic')
    po=PurchaseOrder.objects.create(facility=facility,supplier=Supplier.objects.create(name='Synthetic supplier'),status='approved')
    line=PurchaseOrderLine.objects.create(po=po,item=item,quantity_ordered=1,unit_cost=1)
    receipts=[]
    for n in range(2):
        grn=GoodsReceipt.objects.create(po=po,location=location)
        GoodsReceiptLine.objects.create(grn=grn,po_line=line,item=item,quantity_received=1)
        receipts.append(grn)
    barrier=Barrier(2)
    def run(grn):
        close_old_connections()
        try:
            barrier.wait(timeout=10);post_goods_receipt(grn.pk);return 'posted'
        except ValidationError:return 'rejected'
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,grn) for grn in receipts];assert sorted(f.result(timeout=20) for f in futures)==['posted','rejected']
    assert StockMovement.objects.filter(reason='GRN').count()==1


def test_postgres_overlapping_roster_publication_serializes():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from datetime import timedelta
    from django.utils import timezone
    from apps.accounts.models import Department, StaffProfile
    from apps.operations.workforce_services import create_shift, shift_action
    from apps.operations.models import DutyShift
    facility=Facility.objects.create(name='Roster contention')
    dept=Department.objects.create(facility=facility,name='Clinic')
    manager=User.objects.create_user(username='roster-manager',role='manager')
    doctor=User.objects.create_user(username='roster-doctor',role='clinician')
    for user in (manager,doctor):StaffProfile.objects.update_or_create(user=user,defaults={'facility':facility,'department':dept})
    now=timezone.now();shifts=[create_shift(manager,facility,dept,doctor,manager,now,now+timedelta(hours=8))[0] for _ in range(2)]
    barrier=Barrier(2)
    def run(shift):
        close_old_connections()
        try:
            barrier.wait(timeout=10);shift_action(shift.pk,manager,'publish',1);return 'published'
        except ValidationError:return 'conflict'
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,shift) for shift in shifts]
        assert sorted(f.result(timeout=20) for f in futures)==['conflict','published']
    assert DutyShift.objects.filter(status='published').count()==1


def test_postgres_repeated_clock_in_creates_one_event():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from datetime import timedelta
    from django.utils import timezone
    from apps.accounts.models import Department, StaffProfile
    from apps.operations.workforce_services import create_shift, shift_action, clock
    from apps.operations.models import Attendance
    facility=Facility.objects.create(name='Clock contention');dept=Department.objects.create(facility=facility,name='Clinic')
    manager=User.objects.create_user(username='clock-manager',role='manager');doctor=User.objects.create_user(username='clock-doctor',role='clinician')
    for user in (manager,doctor):StaffProfile.objects.update_or_create(user=user,defaults={'facility':facility,'department':dept})
    now=timezone.now();shift=create_shift(manager,facility,dept,doctor,manager,now-timedelta(minutes=1),now+timedelta(hours=8))[0]
    shift_action(shift.pk,manager,'publish',1);barrier=Barrier(2)
    def run():
        close_old_connections()
        try:barrier.wait(timeout=10);return clock(shift.pk,doctor,'in').pk
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run) for _ in range(2)];results=[f.result(timeout=20) for f in futures]
    assert results[0]==results[1] and Attendance.objects.count()==1


def test_postgres_diagnostic_release_and_cancel_cannot_both_succeed():
    if connection.vendor!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    from apps.accounts.models import StaffProfile
    from apps.orders.models import Order, OrderResult
    from apps.orders.services import cancel_order
    from apps.operations.models import DiagnosticTemplate, DiagnosticWorksheet
    from apps.operations.diagnostic_services import review
    facility=Facility.objects.create(name='Diagnostic contention')
    patient=Patient.objects.create(facility=facility,first_name='Diagnostic',last_name='Race',gender='F')
    actors=[]
    for n in range(2):
        actor=User.objects.create_user(username=f'diagnostic-race-{n}',role='clinician')
        StaffProfile.objects.update_or_create(user=actor,defaults={'facility':facility});actors.append(actor)
    order=Order.objects.create(patient=patient,order_type='imaging',code='SYNTHETIC',billable=False)
    template=DiagnosticTemplate.objects.create(facility=facility,name='Synthetic',version=1,order_type='imaging',fields=[{'key':'findings','label':'Findings','type':'text'}],status='published',created_by=actors[0])
    result=OrderResult.objects.create(order=order,result_text='Synthetic findings',recorded_by=actors[0])
    sheet=DiagnosticWorksheet.objects.create(result=result,template=template,snapshot={'fields':template.fields},answers={'findings':'Synthetic findings'},created_by=actors[0])
    barrier=Barrier(2)
    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if operation=='release':review(sheet.pk,actors[1],'release','Verified')
            else:cancel_order(order.pk,actors[1])
            return operation
        except ValidationError:return 'conflict'
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,op) for op in ('release','cancel')];results=[f.result(timeout=20) for f in futures]
    assert results.count('conflict')==1
    order.refresh_from_db();result.refresh_from_db()
    assert (order.status=='completed' and result.approved_at) or (order.status=='cancelled' and result.approved_at is None)
