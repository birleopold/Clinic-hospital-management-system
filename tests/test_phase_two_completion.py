import uuid
from decimal import Decimal
from datetime import timedelta
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from apps.accounts.models import User, StaffProfile, Facility
from apps.billing.models import Invoice, InvoiceLine, Payment, CashSession
from apps.billing.payment_services import collect_cash
from apps.inventory.models import InventoryItem, Batch, StockMovement, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine, Supplier
from apps.inventory.services import approve_purchase_order, post_goods_receipt
from apps.pharmacy.models import Dispense, DispensingBasket
from apps.pharmacy.checkout_services import checkout
from apps.operations.models import MedicineReturn, Refund, PriceOverride, ReplenishmentRule, StockLocation
from apps.operations.finance_services import request_return, review_return, disburse_refund, authorize_refund, request_price, review_price
from apps.operations.finance_reports import invoice_reconciliation, session_reconciliation, dispense_reconciliation, replenishment_rows
from tests.test_suite import suite
from tests.test_phase_two import catalog, prepared

pytestmark=pytest.mark.django_db


def staff(s,role):
    user=User.objects.create_user(username='phase2-'+role,role=role)
    StaffProfile.objects.update_or_create(user=user,defaults={'facility':s.f})
    return user


def sale(s):
    basket=prepared(s)
    return checkout(basket.pk,s.u,basket.revision,basket.checkout_key)


def test_payment_retry_and_payload_conflict(catalog):
    s=catalog;b=sale(s);cashier=staff(s,'cashier');key=uuid.uuid4()
    payment,created=collect_cash(b.invoice_id,cashier,100,key,'Part payment')
    assert created
    replay,created=collect_cash(b.invoice_id,cashier,100,key,'Part payment')
    assert replay.pk==payment.pk and not created and Payment.objects.count()==1
    with pytest.raises(ValidationError,match='different'):collect_cash(b.invoice_id,cashier,50,key,'Part payment')
    second,_=collect_cash(b.invoice_id,cashier,100,uuid.uuid4())
    b.invoice.refresh_from_db();assert b.invoice.status=='paid' and b.invoice.paid_amount==200
    assert invoice_reconciliation(b.invoice)['paid_difference']==0
    assert session_reconciliation(second.cash_session)['difference']==0
    with pytest.raises(PermissionDenied):collect_cash(b.invoice_id,staff(s,'pharmacy'),1,uuid.uuid4())


def test_api_requires_key_and_returns_same_receipt(catalog):
    s=catalog;b=sale(s);api=APIClient();api.force_authenticate(s.u)
    assert api.post('/api/payments/',{'invoice':b.invoice_id,'amount':'50'}).status_code==400
    payload={'invoice':b.invoice_id,'amount':'50','idempotency_key':str(uuid.uuid4())}
    first=api.post('/api/payments/',payload);second=api.post('/api/payments/',payload)
    assert first.status_code==201 and second.status_code==200
    assert first.data['id']==second.data['id'] and Payment.objects.count()==1


def test_paid_return_quarantine_credit_cash_refund_and_retry(catalog):
    s=catalog;b=sale(s);cashier=staff(s,'cashier');manager=staff(s,'manager')
    collect_cash(b.invoice_id,cashier,200,uuid.uuid4())
    dispense=Dispense.objects.get()
    obj=request_return(dispense.pk,s.u,1,'quarantine','Patient returned one unit','Storage evidence uncertain; isolate stock')
    with pytest.raises(ValidationError,match='different supervisor'):review_return(obj.pk,s.u,'post','Review')
    obj=review_return(obj.pk,manager,'post','Confirmed quantity; quarantine')
    assert obj.amount==100 and obj.returned_batch.quantity_on_hand==1 and obj.returned_batch.quarantined
    b.invoice.refresh_from_db();assert b.invoice.total_amount==100 and b.invoice.paid_amount==200
    refund=obj.refund_links.get().refund
    assert refund.status=='requested' and refund.authorization.created_by==manager
    disburse_refund(refund.pk,cashier);disburse_refund(refund.pk,cashier)
    review_return(obj.pk,manager,'post','Retry')
    b.invoice.refresh_from_db();assert b.invoice.paid_amount==100 and b.invoice.total_amount==100
    assert b.invoice.lines.filter(source_ref=f'return:{obj.pk}').count()==1
    assert StockMovement.objects.filter(ref=f'return:{obj.pk}').count()==1
    assert session_reconciliation(CashSession.objects.get(opened_by=cashier))['expected']==100
    assert invoice_reconciliation(b.invoice)['paid_difference']==0
    check=dispense_reconciliation(dispense)
    assert check['stock_difference']==0 and check['returns'][0]['credit_difference']==0
    s.pi.refresh_from_db();assert s.pi.dispensed_quantity==2  # Return does not authorize another fill.


def test_unpaid_return_and_partial_payment_refund_only_excess(catalog):
    s=catalog;b=sale(s);manager=staff(s,'manager');cashier=staff(s,'cashier')
    collect_cash(b.invoice_id,cashier,50,uuid.uuid4())
    dispense=Dispense.objects.get()
    first=request_return(dispense.pk,s.u,1,'dispose','Damaged','Seal broken')
    review_return(first.pk,manager,'post','Dispose verified')
    assert not Refund.objects.exists()
    first.refresh_from_db();assert first.returned_batch.quantity_on_hand==0
    second=request_return(dispense.pk,s.u,1,'quarantine','Second unit','Isolated')
    review_return(second.pk,manager,'post','Confirmed')
    assert Refund.objects.get().amount==50
    too_many=request_return(dispense.pk,s.u,1,'quarantine','Repeat','Inspect')
    with pytest.raises(ValidationError,match='Already returned'):review_return(too_many.pk,manager,'post','Review')


def test_restock_inspection_rejection_and_expired_batch(catalog):
    s=catalog;sale(s);manager=staff(s,'manager');dispense=Dispense.objects.get()
    with pytest.raises(ValidationError):request_return(dispense.pk,s.u,1,'restock','Return','')
    obj=request_return(dispense.pk,s.u,1,'restock','Return','Sealed with storage evidence')
    s.b.expiry=timezone.localdate()-timedelta(days=1);s.b.save()
    with pytest.raises(ValidationError,match='Expired'):review_return(obj.pk,manager,'post','Review')
    review_return(obj.pk,manager,'reject','Expired, wrong disposition; submit quarantine request')
    obj.refresh_from_db();assert obj.status=='rejected' and not obj.credit_line_id


def test_refund_requires_authorization_and_non_cash_cannot_be_substituted(catalog):
    s=catalog;b=sale(s);cashier=staff(s,'cashier');manager=staff(s,'manager')
    pay,_=collect_cash(b.invoice_id,cashier,100,uuid.uuid4())
    refund=Refund.objects.create(payment=pay,amount=20,created_by=cashier,reason='Cash correction')
    with pytest.raises(ValidationError):disburse_refund(refund.pk,cashier)
    with pytest.raises(PermissionDenied):authorize_refund(refund.pk,cashier,'Self approval')
    authorize_refund(refund.pk,manager,'Approved evidence')
    disburse_refund(refund.pk,cashier)
    external=Payment.objects.create(invoice=b.invoice,amount=50,method='mobile_money')
    noncash=Refund.objects.create(payment=external,amount=10,created_by=cashier,reason='Provider return')
    with pytest.raises(ValidationError,match='non-cash'):authorize_refund(noncash.pk,manager,'Review')


def test_price_exception_separate_approval_and_catalog_change(catalog):
    s=catalog;b=prepared(s);line=b.lines.get();manager=staff(s,'manager')
    request=request_price(line.pk,s.u,75,'Approved customer concession requested')
    with pytest.raises(ValidationError,match='pending price'):checkout(b.pk,s.u,3,b.checkout_key)
    with pytest.raises(ValidationError,match='different supervisor'):review_price(request.pk,s.u,'approve','Self')
    review_price(request.pk,manager,'approve','Within policy')
    b.refresh_from_db();result=checkout(b.pk,s.u,b.revision,b.checkout_key)
    assert result.invoice.total_amount==150
    assert PriceOverride.objects.get().reviewed_by==manager


def test_purchase_approval_receipt_limit_and_creator_rules(catalog):
    s=catalog;store=staff(s,'store');manager=staff(s,'manager')
    po=PurchaseOrder.objects.create(facility=s.f,created_by=store,supplier=Supplier.objects.create(name='Supplier'))
    pl=PurchaseOrderLine.objects.create(po=po,item=s.i,quantity_ordered=10,unit_cost=30)
    with pytest.raises(PermissionDenied):approve_purchase_order(po.pk,store)
    po.created_by=manager;po.save()
    with pytest.raises(ValidationError,match='different supervisor'):approve_purchase_order(po.pk,manager)
    po.created_by=store;po.save();approve_purchase_order(po.pk,manager);approve_purchase_order(po.pk,manager)
    po.refresh_from_db();assert po.approved_by==manager and po.approved_at
    grn=GoodsReceipt.objects.create(po=po,location=s.l)
    line=GoodsReceiptLine.objects.create(grn=grn,po_line=pl,item=s.i,quantity_received=11)
    with pytest.raises(ValidationError,match='exceeds'):post_goods_receipt(grn.pk)
    assert not StockMovement.objects.filter(ref=f'GRN:{grn.pk}').exists()
    line.quantity_received=10;line.save();post_goods_receipt(grn.pk);post_goods_receipt(grn.pk)
    assert StockMovement.objects.filter(ref=f'GRN:{grn.pk}').count()==1


def test_replenishment_subtracts_approved_unreceived_and_excludes_transfers(catalog):
    s=catalog
    destination=StockLocation.objects.create(facility=s.f,name='Dispensing shelf')
    ReplenishmentRule.objects.create(facility=s.f,item=s.i,lead_days=10,review_days=10,safety_days=10,preferred_location=destination)
    StockMovement.objects.create(item=s.i,batch=s.b,direction='out',quantity=30,reason='dispense')
    StockMovement.objects.create(item=s.i,batch=s.b,direction='out',quantity=900,reason='transfer')
    po=PurchaseOrder.objects.create(facility=s.f,supplier=Supplier.objects.create(name='Incoming'),status='approved')
    pl=PurchaseOrderLine.objects.create(po=po,item=s.i,quantity_ordered=15)
    grn=GoodsReceipt.objects.create(po=po,location=s.l,posted=True)
    GoodsReceiptLine.objects.create(grn=grn,po_line=pl,item=s.i,quantity_received=5)
    row=replenishment_rows(s.f,[s.i])[0]
    assert row['consumed']==30 and row['target']==30 and row['open_po']==10 and row['suggested']==10
    assert row['transfers'][0]['destination']==destination and row['transfers'][0]['quantity']==10


def test_finance_inventory_and_return_scope_and_ui(catalog):
    s=catalog;b=sale(s)
    for url in ['/suite/finance/',f'/suite/finance/invoice/{b.invoice_id}/','/suite/returns/','/suite/price-reviews/','/suite/replenishment/',f'/suite/stock/batch/{s.b.pk}/']:
        assert s.client.get(url).status_code==200,url
    other=staff(s,'manager');StaffProfile.objects.filter(user=other).update(facility=Facility.objects.create(name='Elsewhere'))
    s.client.force_login(other)
    assert s.client.get(f'/suite/finance/invoice/{b.invoice_id}/').status_code==404
    assert s.client.get(f'/suite/stock/batch/{s.b.pk}/').status_code==404
    response=s.client.get('/suite/finance/');assert b.invoice not in response.context['page']
    s.client.force_login(staff(s,'pharmacy'))
    assert s.client.get('/suite/finance/').status_code==403


def test_invoice_ui_payment_and_return_form(catalog):
    s=catalog;b=sale(s);url=reverse('suite-invoice-detail',args=[b.invoice_id])
    assert s.client.post(url,{'amount':'200','idempotency_key':str(uuid.uuid4()),'notes':'Counter'}).status_code==302
    disp=Dispense.objects.get()
    response=s.client.post('/suite/returns/',{'dispense':disp.pk,'quantity':1,'disposition':'quarantine','reason':'Returned','inspection':'Isolate'})
    assert response.status_code==302 and MedicineReturn.objects.count()==1
