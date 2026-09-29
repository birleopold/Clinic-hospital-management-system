from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core import signing
from django.urls import reverse
from apps.accounts.models import User, Facility, StaffProfile
from apps.demographics.models import Patient
from apps.inventory.models import InventoryItem, Batch, StockMovement, Supplier, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine
from apps.pharmacy.models import Prescription, PrescriptionItem, Dispense, Backorder
from apps.billing.models import Invoice, Payment, CashSession
from apps.orders.models import Order, OrderResult
from apps.operations.models import StockLocation, StockCount, Refund, Bed, Admission, ClinicalEntry, PortalGrant
from apps.operations.services import post_count, approve_refund, transfer_stock
from apps.inventory.services import post_goods_receipt
from apps.appointments.models import Appointment, QueueTicket

pytestmark = pytest.mark.django_db

@pytest.fixture
def suite(client):
    f=Facility.objects.create(name='Test clinic')
    u=User.objects.create_user(username='suite-admin',password='test',role='admin')
    StaffProfile.objects.update_or_create(user=u,defaults={'facility':f})
    p=Patient.objects.create(first_name='Test',last_name='Patient',gender='F',facility=f)
    l=StockLocation.objects.create(facility=f,name='Pharmacy')
    i=InventoryItem.objects.create(code='MED',name='Medicine')
    b=Batch.objects.create(item=i,location=l,quantity_on_hand=10,expiry=timezone.localdate()+timedelta(days=100))
    rx=Prescription.objects.create(patient=p)
    pi=PrescriptionItem.objects.create(prescription=rx,item_code='MED',quantity=5)
    client.force_login(u)
    return SimpleNamespace(f=f,u=u,p=p,l=l,i=i,b=b,pi=pi,client=client)

def dispense(s,qty=2,**kw):
    return Dispense.objects.create(patient=s.p,prescription_item=s.pi,item_code='MED',quantity=qty,batch=kw.get('batch',s.b))

def test_dispense_posts_stock_and_prescription_once(suite):
    d=dispense(suite)
    suite.b.refresh_from_db();suite.pi.refresh_from_db()
    assert suite.b.quantity_on_hand==8 and suite.pi.dispensed_quantity==2
    assert StockMovement.objects.get(ref=f'dispense:{d.pk}').quantity==2
    with pytest.raises(ValidationError): d.save()
    with pytest.raises(ValidationError): dispense(suite,4)
    assert Dispense.objects.count()==1

@pytest.mark.parametrize('change',[{'expiry':timezone.localdate()-timedelta(days=1)},{'quarantined':True},{'quantity_on_hand':1}])
def test_unusable_stock_cannot_be_dispensed(suite,change):
    Batch.objects.filter(pk=suite.b.pk).update(**change)
    with pytest.raises(ValidationError): dispense(suite)
    assert not Dispense.objects.exists()
    assert not Invoice.objects.exists()

def test_other_facility_stock_rejected(suite):
    other=Facility.objects.create(name='Other')
    location=StockLocation.objects.create(facility=other,name='Store')
    Batch.objects.filter(pk=suite.b.pk).update(location=location)
    with pytest.raises(ValidationError): dispense(suite)

def test_receipt_idempotent_does_not_fulfill_backorder(suite):
    po=PurchaseOrder.objects.create(supplier=Supplier.objects.create(name='Supplier'),status='approved')
    pl=PurchaseOrderLine.objects.create(po=po,item=suite.i,quantity_ordered=3)
    grn=GoodsReceipt.objects.create(po=po,location=suite.l)
    GoodsReceiptLine.objects.create(grn=grn,po_line=pl,item=suite.i,quantity_received=3)
    bo=Backorder.objects.create(patient=suite.p,prescription_item=suite.pi,item_code='MED',quantity=3)
    post_goods_receipt(grn.pk);post_goods_receipt(grn.pk)
    assert StockMovement.objects.filter(ref=f'GRN:{grn.pk}').count()==1
    assert not Dispense.objects.exists()
    bo.refresh_from_db();assert bo.fulfilled_quantity==0
    po.refresh_from_db();assert po.status=='received'

def test_stock_count_rejects_stale_balance(suite):
    count=StockCount.objects.create(batch=suite.b,expected=10,counted=9,reason='Count',created_by=suite.u)
    boss=User.objects.create_user(username='boss',role='manager')
    Batch.objects.filter(pk=suite.b.pk).update(quantity_on_hand=8)
    with pytest.raises(ValidationError): post_count(count.pk,boss)
    Batch.objects.filter(pk=suite.b.pk).update(quantity_on_hand=10)
    post_count(count.pk,boss);post_count(count.pk,boss)
    suite.b.refresh_from_db();assert suite.b.quantity_on_hand==9
    assert StockMovement.objects.filter(ref=f'count:{count.pk}').count()==1

def test_transfer_conserves_quantity(suite):
    dest=StockLocation.objects.create(facility=suite.f,name='Main store')
    target=transfer_stock(suite.b.pk,dest,4,suite.u)
    suite.b.refresh_from_db()
    assert suite.b.quantity_on_hand+target.quantity_on_hand==10
    assert StockMovement.objects.count()==2

def test_refund_repayment_reconciles(suite):
    from rest_framework.test import APIClient
    inv=Invoice.objects.create(patient=suite.p,total_amount=100,paid_amount=100,status='paid')
    session=CashSession.objects.create(opened_by=suite.u,expected_cash=100)
    pay=Payment.objects.create(invoice=inv,cash_session=session,amount=100)
    refund=Refund.objects.create(payment=pay,amount=30,reason='Correction',created_by=suite.u)
    approve_refund(refund.pk,suite.u);approve_refund(refund.pk,suite.u)
    inv.refresh_from_db();session.refresh_from_db()
    assert inv.paid_amount==70 and session.expected_cash==70
    api=APIClient();api.force_authenticate(suite.u)
    response=api.post('/api/payments/',{'invoice':inv.pk,'amount':'30.00','method':'cash'})
    assert response.status_code==201,response.data
    inv.refresh_from_db();session.refresh_from_db()
    assert inv.paid_amount==100 and session.expected_cash==100

def test_portal_requires_grant_and_filters_draft_results(suite):
    grant=PortalGrant.objects.create(patient=suite.p,created_by=suite.u,expires_at=timezone.now()+timedelta(hours=1))
    order=Order.objects.create(patient=suite.p,order_type='lab',code='LAB',billable=False)
    OrderResult.objects.create(order=order,result_text='PRIVATE_DRAFT')
    OrderResult.objects.create(order=order,result_text='APPROVED_RESULT',approved_at=timezone.now(),approved_by=suite.u)
    token=signing.dumps({'p':suite.p.pk,'g':str(grant.key)},salt='patient-portal')
    response=suite.client.get(reverse('portal-view',args=[token]))
    assert response.status_code==200
    assert b'PRIVATE_DRAFT' not in response.content and b'APPROVED_RESULT' in response.content
    grant.revoked_at=timezone.now();grant.save()
    assert suite.client.get(reverse('portal-view',args=[token])).status_code==403

def test_all_suite_screens_render(suite):
    from apps.operations.views import MODULES
    for slug in MODULES:
        response=suite.client.get(reverse('suite-collection',args=[slug]))
        assert response.status_code==200,(slug,response.status_code)
    for url in ['/suite/','/suite/stock/',reverse('suite-patient',args=[suite.p.pk])]:
        assert suite.client.get(url).status_code==200,url

def test_cross_facility_admission_and_occupied_bed_rejected(suite):
    bed=Bed.objects.create(facility=suite.f,ward='General',name='1')
    response=suite.client.post('/suite/admissions/',{'patient':suite.p.pk,'bed':bed.pk,'reason':'Observation'})
    assert response.status_code==302
    p2=Patient.objects.create(first_name='Second',last_name='Patient',gender='M',facility=suite.f)
    response=suite.client.post('/suite/admissions/',{'patient':p2.pk,'bed':bed.pk,'reason':'Observation'})
    assert response.status_code==200 and Admission.objects.count()==1
    a=Admission.objects.get()
    response=suite.client.post(f'/suite/admissions/{a.pk}/discharge/',{'reason':'Discharge summary'})
    assert response.status_code==302
    a.refresh_from_db();assert a.discharged_at

def test_reception_denied_clinical_history(suite):
    suite.u.role='reception';suite.u.save()
    assert suite.client.get('/suite/clinical/').status_code==403
    assert suite.client.get(reverse('suite-patient',args=[suite.p.pk])).status_code==403

def test_cross_facility_writable_relation_rejected(suite):
    other=Patient.objects.create(first_name='Other',last_name='Patient',gender='F',facility=Facility.objects.create(name='Elsewhere'))
    response=suite.client.post('/suite/clinical/',{'patient':other.pk,'kind':'allergy','text':'Must not save'})
    assert response.status_code==200 and not ClinicalEntry.objects.exists()

def test_appointment_overlap_and_queue_transitions(suite):
    start=timezone.now()+timedelta(days=1)
    Appointment.objects.create(patient=suite.p,clinician=suite.u,scheduled_for=start)
    with pytest.raises(ValidationError): Appointment.objects.create(patient=suite.p,clinician=suite.u,scheduled_for=start+timedelta(minutes=10))
    ticket=QueueTicket.objects.create(patient=suite.p,service='triage')
    ticket.status='in_service';ticket.save();started=ticket.started_at
    ticket.save();assert ticket.started_at==started
    ticket.status='done';ticket.save()
    ticket.status='waiting'
    with pytest.raises(ValidationError): ticket.save()

def test_receipt_failure_rolls_back_all_stock(suite):
    po=PurchaseOrder.objects.create(supplier=Supplier.objects.create(name='Supplier'),status='approved',facility=suite.f)
    grn=GoodsReceipt.objects.create(po=po,location=suite.l)
    GoodsReceiptLine.objects.create(grn=grn,item=suite.i,quantity_received=3)
    GoodsReceiptLine.objects.create(grn=grn,item=suite.i,quantity_received=-1)
    with pytest.raises(ValidationError): post_goods_receipt(grn.pk)
    grn.refresh_from_db()
    assert not grn.posted and not StockMovement.objects.exists()
    assert Batch.objects.count()==1

def test_lab_release_requires_second_reviewer_and_records_acknowledgment(suite):
    order=Order.objects.create(patient=suite.p,order_type='lab',code='LAB',billable=False)
    result=OrderResult.objects.create(order=order,result_text='Result',recorded_by=suite.u,critical=True)
    url=f'/suite/results/{result.pk}/release/'
    suite.client.post(url)
    result.refresh_from_db();assert result.approved_at is None
    reviewer=User.objects.create_user(username='reviewer',role='clinician')
    StaffProfile.objects.update_or_create(user=reviewer,defaults={'facility':suite.f})
    suite.client.force_login(reviewer)
    assert suite.client.post(url).status_code==302
    result.refresh_from_db();assert result.approved_by==reviewer
    suite.client.post(f'/suite/results/{result.pk}/acknowledge/')
    result.refresh_from_db();assert result.acknowledged_by==reviewer

def test_reminder_requires_consent_and_noop_never_marks_sent(suite):
    from apps.operations.models import Reminder
    from django.core.management import call_command
    from django.core.management.base import CommandError
    suite.p.phone='+256700000000';suite.p.save()
    response=suite.client.post('/suite/reminders/',{'patient':suite.p.pk,'scheduled_for':'2026-09-29T09:00','body':'Appointment reminder'})
    assert response.status_code==200 and not Reminder.objects.exists()
    job=Reminder.objects.create(patient=suite.p,created_by=suite.u,scheduled_for=timezone.now(),body='Reminder',consent_confirmed=True)
    with pytest.raises(CommandError): call_command('dispatch_reminders')
    job.refresh_from_db();assert job.status=='pending'

def test_inpatient_transfer_preserves_history(suite):
    a=Bed.objects.create(facility=suite.f,ward='General',name='A')
    b=Bed.objects.create(facility=suite.f,ward='General',name='B')
    admission=Admission.objects.create(patient=suite.p,bed=a,reason='Observation',created_by=suite.u)
    assert suite.client.post(f'/suite/admissions/{admission.pk}/transfer/',{'bed':b.pk}).status_code==302
    admission.refresh_from_db();assert admission.bed==b
    assert admission.history.count()==2

def test_non_superuser_cannot_use_legacy_unassigned_stock(suite):
    Batch.objects.filter(pk=suite.b.pk).update(location=None)
    response=suite.client.get(reverse('batch-list'))
    assert response.status_code==200 and response.json()['count']==0
    with pytest.raises(ValidationError): dispense(suite)

def test_nursing_entry_after_discharge_rejected(suite):
    from apps.operations.models import NursingObservation
    bed=Bed.objects.create(facility=suite.f,ward='Ward',name='1')
    admission=Admission.objects.create(patient=suite.p,bed=bed,reason='Observation',created_by=suite.u,discharged_at=timezone.now())
    response=suite.client.post('/suite/observations/',{'admission':admission.pk,'observations':'Should not save'})
    assert response.status_code==200 and not NursingObservation.objects.exists()

def test_released_result_cannot_be_edited_through_api(suite):
    from rest_framework.test import APIClient
    order=Order.objects.create(patient=suite.p,order_type='lab',code='LAB',billable=False)
    result=OrderResult.objects.create(order=order,result_text='Original',approved_at=timezone.now(),approved_by=suite.u)
    api=APIClient();api.force_authenticate(suite.u)
    response=api.patch(f'/api/order-results/{result.pk}/',{'result_text':'Changed'})
    assert response.status_code==400,response.status_code
    result.refresh_from_db();assert result.result_text=='Original'

def test_credit_is_idempotent_and_separate_from_cash_refund(suite):
    from apps.operations.models import InvoiceCredit
    from apps.operations.services import approve_credit
    from apps.billing.models import InvoiceLine
    invoice=Invoice.objects.create(patient=suite.p,total_amount=100)
    InvoiceLine.objects.create(invoice=invoice,code='SERVICE',quantity=1,unit_price=100,source_ref='service:test')
    credit=InvoiceCredit.objects.create(invoice=invoice,amount=25,reason='Approved correction',created_by=suite.u)
    approve_credit(credit.pk,suite.u);approve_credit(credit.pk,suite.u)
    invoice.refresh_from_db()
    assert invoice.total_amount==75
    assert invoice.lines.filter(source_ref=f'credit:{credit.pk}').count()==1
    assert not Refund.objects.exists()

def test_room_cannot_be_double_booked_by_different_clinicians(suite):
    from apps.operations.models import ServiceRoom
    room=ServiceRoom.objects.create(facility=suite.f,name='Consultation 1')
    second=User.objects.create_user(username='second-clinician',role='clinician')
    start=timezone.now()+timedelta(days=1)
    Appointment.objects.create(patient=suite.p,clinician=suite.u,room=room,scheduled_for=start)
    with pytest.raises(ValidationError):
        Appointment.objects.create(patient=suite.p,clinician=second,room=room,scheduled_for=start)

def test_portal_grant_creation_requires_post(suite):
    url=reverse('portal-token-create')+f'?patient_id={suite.p.pk}'
    assert suite.client.get(url).status_code==200
    assert not PortalGrant.objects.exists()
    assert suite.client.post(url).status_code==200
    assert PortalGrant.objects.filter(patient=suite.p).count()==1
