import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import PermissionDenied,ValidationError
from django.utils import timezone
from apps.accounts.models import User,StaffProfile,ApprovalGrant,ApprovalPolicy
from apps.accounts import approval_services as s
from apps.operations import management_services as management,settlement_services as settlement
from apps.operations.models import OperatingBudget
from tests.test_workforce import team
from tests.test_end_to_end_completion import expense,payment_data

pytestmark=pytest.mark.django_db

@pytest.fixture
def administrator(team):
    u=User.objects.create_user('matrix-admin',role='admin')
    StaffProfile.objects.update_or_create(user=u,defaults={'facility':team.f})
    return u

def grant_data(t,operation='expense',maximum=800):
    return dict(facility=t.f,operation=operation,approver=t.manager2,maximum=Decimal(maximum),starts_at=timezone.now()-timedelta(minutes=1),ends_at=timezone.now()+timedelta(days=1),reason='Synthetic timed delegation',request_key=uuid.uuid4())

def test_policy_limit_independence_revocation_and_atomic_expense(team,administrator):
    t=team;obj=expense(t);obj.status='requested';obj.save()
    policy=s.configure(administrator,t.f.pk,'expense',True,0,'Apply facility limits')
    with pytest.raises(ValidationError,match='authority'):management.decide(type(obj),obj.pk,t.manager2,'approved','Reviewed')
    obj.refresh_from_db();assert obj.status=='requested'
    data=grant_data(t,maximum=799);grant=s.grant(administrator,**data)
    assert s.grant(administrator,**data).pk==grant.pk
    with pytest.raises(ValidationError,match='authority'):management.decide(type(obj),obj.pk,t.manager2,'approved','Reviewed')
    s.revoke(administrator,grant.pk,'Increase reviewed limit')
    grant=s.grant(administrator,**grant_data(t,maximum=800))
    with pytest.raises(ValidationError,match='different supervisor'):management.decide(type(obj),obj.pk,t.manager,'approved','Self')
    management.decide(type(obj),obj.pk,t.manager2,'approved','Reviewed')
    obj.refresh_from_db();assert obj.status=='approved'
    s.revoke(administrator,grant.pk,'Ended delegation')
    assert ApprovalPolicy.objects.get(pk=policy.pk).enabled
    with pytest.raises(ValidationError,match='authority'):s.require(t.manager2,t.f.pk,'expense',1)
    # A completed operation remains retry-safe after authority has expired.
    management.decide(type(obj),obj.pk,t.manager2,'approved','Retry')

def test_future_expired_cross_facility_and_self_grants(team,administrator):
    t=team;s.configure(administrator,t.f.pk,'credit',True,0,'Controlled credits')
    data=grant_data(t,operation='credit')
    data['starts_at']=timezone.now()+timedelta(hours=1)
    grant=s.grant(administrator,**data)
    with pytest.raises(ValidationError,match='authority'):s.require(t.manager2,t.f.pk,'credit',10)
    ApprovalGrant.objects.filter(pk=grant.pk).update(starts_at=timezone.now()-timedelta(days=2),ends_at=timezone.now()-timedelta(days=1))
    with pytest.raises(ValidationError,match='authority'):s.require(t.manager2,t.f.pk,'credit',10)
    with pytest.raises(PermissionDenied):s.require(t.outsider,t.f.pk,'credit',10)
    with pytest.raises(ValidationError,match='Another administrator'):s.grant(administrator,**{**grant_data(t),'approver':administrator})
    with pytest.raises(ValidationError,match='assigned'):s.grant(administrator,**{**grant_data(t),'approver':t.outsider})
    with pytest.raises(ValidationError,match='finite'):s.grant(administrator,**{**grant_data(t),'maximum':Decimal('NaN')})
    with pytest.raises(ValidationError,match='changed'):s.configure(administrator,t.f.pk,'credit',False,0,'Stale revision')

def test_matrix_ui_scopes_retries_enable_and_revoke(client,team,administrator):
    t=team;client.force_login(administrator)
    response=client.get('/accounts/approvals/')
    assert response.status_code==200 and b'Grant timed approval authority' in response.content
    data=grant_data(t);data.update(action='grant',facility=t.f.pk,approver=t.manager2.pk)
    assert client.post('/accounts/approvals/',data).status_code==302
    assert client.post('/accounts/approvals/',data).status_code==302
    assert ApprovalGrant.objects.count()==1
    grant=ApprovalGrant.objects.get()
    assert client.post('/accounts/approvals/',{'action':'policy','facility':t.f.pk,'operation':'expense','revision':0,'enabled':1,'reason':'Reviewed policy'}).status_code==302
    assert ApprovalPolicy.objects.get().enabled
    assert client.post('/accounts/approvals/',{'action':'revoke','grant':grant.pk,'reason':'Finished'}).status_code==302
    grant.refresh_from_db();assert grant.revoked_at and grant.revoked_by==administrator
    assert client.post('/accounts/approvals/',{**data,'request_key':uuid.uuid4(),'facility':t.other.pk}).status_code==200
    assert ApprovalGrant.objects.count()==1
    client.force_login(t.manager)
    assert client.get('/accounts/approvals/').status_code==403

def test_settlement_matrix_checks_actual_reconciled_amount(team,administrator):
    t=team;obj=expense(t)
    evidence=settlement.record_settlement(t.manager,obj.pk,**payment_data())
    s.configure(administrator,t.f.pk,'settlement',True,0,'Independent evidence limits')
    with pytest.raises(ValidationError,match='authority'):settlement.reconcile(t.manager2,evidence.pk,'confirmed','Reviewed')
    evidence.refresh_from_db();assert evidence.status=='pending'
    s.grant(administrator,**grant_data(t,operation='settlement',maximum=300))
    settlement.reconcile(t.manager2,evidence.pk,'confirmed','Bank statement checked')
    evidence.refresh_from_db();assert evidence.status=='confirmed'

@pytest.mark.parametrize('operation',['purchase','budget','expense','settlement','credit','refund','return','price'])
def test_all_enabled_operations_require_matching_grants(team,administrator,operation):
    t=team;s.configure(administrator,t.f.pk,operation,True,0,'Enforce reviewed policy')
    with pytest.raises(ValidationError,match='authority'):s.require(t.manager2,t.f.pk,operation,100)
    grant=s.grant(administrator,**grant_data(t,operation=operation,maximum=100))
    s.require(t.manager2,t.f.pk,operation,100)
    with pytest.raises(ValidationError,match='authority'):s.require(t.manager2,t.f.pk,operation,Decimal('100.01'))

# Real transaction entry points: a denied grant must leave stock and ledgers intact.
from tests.test_suite import suite
from tests.test_phase_two import catalog,prepared
from tests.test_phase_two_completion import sale,staff

def catalog_authority(catalog,operation,maximum):
    admin=staff(catalog,'admin');manager=staff(catalog,'manager')
    s.configure(admin,catalog.f.pk,operation,True,0,'Synthetic policy')
    data=dict(facility=catalog.f,operation=operation,approver=manager,maximum=Decimal(maximum),starts_at=timezone.now()-timedelta(minutes=1),ends_at=timezone.now()+timedelta(days=1),reason='Synthetic authority',request_key=uuid.uuid4())
    s.grant(admin,**data)
    return admin,manager

def test_purchase_transaction_limit(catalog):
    from apps.inventory.models import Supplier,PurchaseOrder,PurchaseOrderLine
    from apps.inventory.services import approve_purchase_order
    c=catalog;admin,manager=catalog_authority(c,'purchase',199)
    po=PurchaseOrder.objects.create(facility=c.f,supplier=Supplier.objects.create(name='Synthetic supplier'),created_by=c.u)
    PurchaseOrderLine.objects.create(po=po,item=c.i,quantity_ordered=2,unit_cost=100)
    with pytest.raises(ValidationError,match='authority'):approve_purchase_order(po.pk,manager)
    po.refresh_from_db();assert po.status=='draft'
    ApprovalGrant.objects.filter(approver=manager).update(maximum=200)
    approve_purchase_order(po.pk,manager);po.refresh_from_db();assert po.status=='approved'

def test_credit_transaction_limit(catalog):
    from apps.operations.models import InvoiceCredit
    from apps.operations.finance_services import approve_invoice_credit
    c=catalog;b=sale(c);admin,manager=catalog_authority(c,'credit',99)
    obj=InvoiceCredit.objects.create(invoice=b.invoice,amount=100,reason='Synthetic correction',created_by=c.u)
    with pytest.raises(ValidationError,match='authority'):approve_invoice_credit(obj.pk,manager)
    b.invoice.refresh_from_db();assert b.invoice.total_amount==200
    assert not b.invoice.lines.filter(source_ref=f'credit:{obj.pk}').exists()
    ApprovalGrant.objects.filter(approver=manager).update(maximum=100)
    approve_invoice_credit(obj.pk,manager);b.invoice.refresh_from_db();assert b.invoice.total_amount==100

def test_price_transaction_limit_measures_whole_line(catalog):
    from apps.operations.finance_services import request_price,review_price
    c=catalog;b=prepared(c);admin,manager=catalog_authority(c,'price',39)
    line=b.lines.get();obj=request_price(line.pk,c.u,80,'Synthetic price request')
    with pytest.raises(ValidationError,match='authority'):review_price(obj.pk,manager,'approve','Reviewed')
    line.refresh_from_db();assert line.unit_price==100
    ApprovalGrant.objects.filter(approver=manager).update(maximum=40)
    review_price(obj.pk,manager,'approve','Reviewed');line.refresh_from_db();assert line.unit_price==80

def test_return_refund_limit_rolls_back_stock_and_credit(catalog):
    from apps.billing.payment_services import collect_cash
    from apps.pharmacy.models import Dispense
    from apps.inventory.models import StockMovement
    from apps.operations.models import Refund,RefundAuthorization
    from apps.operations.finance_services import request_return,review_return
    c=catalog;b=sale(c);cashier=staff(c,'cashier');collect_cash(b.invoice_id,cashier,200,uuid.uuid4())
    admin,manager=catalog_authority(c,'refund',99)
    obj=request_return(Dispense.objects.get().pk,c.u,1,'quarantine','Synthetic return','Synthetic inspection')
    with pytest.raises(ValidationError,match='authority'):review_return(obj.pk,manager,'post','Reviewed')
    obj.refresh_from_db();b.invoice.refresh_from_db()
    assert obj.status=='requested' and b.invoice.total_amount==200
    assert not StockMovement.objects.filter(ref=f'return:{obj.pk}').exists() and not Refund.objects.exists()
    ApprovalGrant.objects.filter(approver=manager).update(maximum=100)
    review_return(obj.pk,manager,'post','Reviewed')
    assert RefundAuthorization.objects.get().authorized_amount==100

def test_refund_snapshot_rejects_changed_amount_and_revalidates_legacy(catalog):
    from apps.billing.payment_services import collect_cash
    from apps.operations.models import Refund,RefundAuthorization
    from apps.operations.finance_services import authorize_refund,disburse_refund
    c=catalog;b=sale(c);cashier=staff(c,'cashier');payment,_=collect_cash(b.invoice_id,cashier,200,uuid.uuid4())
    admin,manager=catalog_authority(c,'refund',100)
    refund=Refund.objects.create(payment=payment,amount=100,reason='Synthetic correction',created_by=cashier)
    legacy=RefundAuthorization.objects.create(refund=refund,created_by=manager,reason='Legacy evidence')
    with pytest.raises(ValidationError,match='changed'):disburse_refund(refund.pk,cashier)
    authorize_refund(refund.pk,manager,'Rechecked source payment')
    legacy.refresh_from_db();assert legacy.authorized_amount==100 and legacy.payment_reference==payment.pk
    Refund.objects.filter(pk=refund.pk).update(amount=101)
    with pytest.raises(ValidationError,match='changed'):disburse_refund(refund.pk,cashier)
    refund.refresh_from_db();assert refund.status=='requested'
    assert RefundAuthorization.objects.count()==1
