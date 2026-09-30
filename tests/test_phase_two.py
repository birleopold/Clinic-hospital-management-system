from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Facility, StaffProfile, User
from apps.demographics.models import Patient
from apps.inventory.models import InventoryItem, Batch, StockMovement
from apps.billing.models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment
from apps.operations.models import PackageUnit, DuplicateReview
from apps.pharmacy.models import (MedicineProfile, MedicineBarcode, PharmacyPolicy,
    DispensingBasket, BasketLine, BasketAllocation, Dispense, Prescription, PrescriptionItem)
from apps.pharmacy.checkout_services import create_basket, add_item, checkout, change_basket
from tests.test_suite import suite

pytestmark=pytest.mark.django_db


@pytest.fixture
def catalog(suite):
    MedicineProfile.objects.create(item=suite.i,reviewed=True,generic_name='Synthetic medicine',strength='Test strength',dosage_form='Test form',route='Test route')
    prices=PriceList.objects.create(name='Basket prices',effective_date=timezone.localdate())
    PriceListItem.objects.create(pricelist=prices,code=suite.i.code,name=suite.i.name,amount=100)
    return suite


def prepared(s):
    basket=create_basket(s.p.pk,s.u)
    add_item(basket.pk,s.u,1,'MED',2,s.pi.pk)
    basket.refresh_from_db()
    return basket


def test_checkout_fefo_split_invoice_retry_and_labels(catalog):
    s=catalog
    s.b.quantity_on_hand=1;s.b.save()
    later=Batch.objects.create(item=s.i,location=s.l,quantity_on_hand=4,expiry=s.b.expiry+timedelta(days=10),batch_no='LATER')
    invalid=Batch.objects.create(item=s.i,location=s.l,quantity_on_hand=20,expiry=timezone.localdate()-timedelta(days=1))
    basket=prepared(s)
    result=checkout(basket.pk,s.u,basket.revision,basket.checkout_key)
    assert result.status=='completed'
    allocations=list(BasketAllocation.objects.select_related('dispense').order_by('pk'))
    assert [a.dispense.batch_id for a in allocations]==[s.b.pk,later.pk]
    assert [a.dispense.quantity for a in allocations]==[1,1]
    assert result.invoice.total_amount==200 and result.invoice.status==Invoice.READY
    assert result.invoice.lines.count()==2 and not Payment.objects.exists()
    assert checkout(basket.pk,s.u,1,basket.checkout_key).invoice_id==result.invoice_id
    assert Dispense.objects.count()==2 and Invoice.objects.count()==1
    assert StockMovement.objects.filter(reason='dispense').count()==2
    s.pi.refresh_from_db();assert s.pi.dispensed_quantity==2
    invalid.refresh_from_db();assert invalid.quantity_on_hand==20
    response=s.client.get(reverse('pharmacy-basket-labels',args=[basket.pk]))
    assert response.status_code==200 and b'Test strength' in response.content and b'LATER' in response.content


def test_checkout_stock_failure_rolls_back_entire_basket(catalog):
    s=catalog;basket=prepared(s)
    extra=InventoryItem.objects.create(code='OTHER',name='Other medicine')
    MedicineProfile.objects.create(item=extra,reviewed=True,prescription_required=False)
    PharmacyPolicy.objects.create(facility=s.f,allow_retail=True)
    PriceListItem.objects.create(pricelist=PriceList.objects.first(),code='OTHER',name='Other',amount=50)
    add_item(basket.pk,s.u,2,'OTHER',1)
    with pytest.raises(ValidationError):checkout(basket.pk,s.u,3,basket.checkout_key)
    assert not Invoice.objects.exists() and not Dispense.objects.exists()
    s.b.refresh_from_db();assert s.b.quantity_on_hand==10
    basket.refresh_from_db();assert basket.status=='open'


def test_hold_cancel_stale_revision_and_closed_basket(catalog):
    s=catalog;basket=prepared(s)
    change_basket(basket.pk,s.u,2,'hold')
    with pytest.raises(ValidationError):add_item(basket.pk,s.u,3,'MED',1,s.pi.pk)
    with pytest.raises(ValidationError):change_basket(basket.pk,s.u,2,'resume')
    change_basket(basket.pk,s.u,3,'resume')
    change_basket(basket.pk,s.u,4,'cancel')
    with pytest.raises(ValidationError):checkout(basket.pk,s.u,5,basket.checkout_key)
    assert not Dispense.objects.exists()


def test_barcode_package_conversion_snapshot_and_rx_limit(catalog):
    s=catalog;pack=PackageUnit.objects.create(item=s.i,name='Pack',units_per_pack=2)
    MedicineBarcode.objects.create(code='00012345',item=s.i,package=pack)
    basket=create_basket(s.p.pk,s.u)
    line=add_item(basket.pk,s.u,1,'00012345',2,s.pi.pk)
    assert line.quantity==4 and line.packs==2 and line.units_per_pack==2
    with pytest.raises(ValidationError):add_item(basket.pk,s.u,2,'00012345',1,s.pi.pk)
    pack.units_per_pack=3;pack.save()
    with pytest.raises(ValidationError,match='conversion changed'):checkout(basket.pk,s.u,2,basket.checkout_key)
    assert not Dispense.objects.exists()


def test_price_and_prescription_changes_require_new_review(catalog):
    s=catalog;basket=prepared(s)
    PriceListItem.objects.update(amount=200)
    with pytest.raises(ValidationError,match='price changed'):checkout(basket.pk,s.u,2,basket.checkout_key)
    PriceListItem.objects.update(amount=100)
    s.pi.dose='Changed direction';s.pi.save()
    with pytest.raises(ValidationError,match='Prescription changed'):checkout(basket.pk,s.u,2,basket.checkout_key)
    assert not Invoice.objects.exists()


def test_prescription_and_retail_policy_enforced_on_all_dispensing(catalog):
    s=catalog;basket=create_basket(s.p.pk,s.u)
    with pytest.raises(ValidationError,match='requires a prescription'):add_item(basket.pk,s.u,1,'MED',1)
    MedicineProfile.objects.filter(item=s.i).update(prescription_required=False)
    with pytest.raises(ValidationError,match='not enabled'):add_item(basket.pk,s.u,1,'MED',1)
    PharmacyPolicy.objects.create(facility=s.f,allow_retail=True)
    add_item(basket.pk,s.u,1,'MED',1)
    PharmacyPolicy.objects.filter(facility=s.f).update(allow_retail=False)
    with pytest.raises(ValidationError):checkout(basket.pk,s.u,2,basket.checkout_key)
    with pytest.raises(ValidationError):Dispense.objects.create(patient=s.p,batch=s.b,item_code='MED',quantity=1)
    assert not Dispense.objects.exists()


def test_facility_roles_and_patient_matching(catalog):
    s=catalog;basket=prepared(s)
    f=Facility.objects.create(name='Other')
    other=User.objects.create_user(username='other-dispenser',role='pharmacy')
    StaffProfile.objects.update_or_create(user=other,defaults={'facility':f})
    with pytest.raises(PermissionDenied):checkout(basket.pk,other,2,basket.checkout_key)
    s.client.force_login(other)
    assert s.client.get(reverse('pharmacy-basket',args=[basket.pk])).status_code==404
    assert s.client.get(reverse('pharmacy-basket-labels',args=[basket.pk])).status_code==404
    assert s.client.get(reverse('pharmacy-basket-patients'),{'q':'Test'}).json()['results']==[]
    other.role='cashier';other.save()
    assert s.client.get(reverse('pharmacy-baskets')).status_code==403
    wrong=Patient.objects.create(first_name='Other',last_name='Patient',gender='F',facility=s.f)
    pi=PrescriptionItem.objects.create(prescription=Prescription.objects.create(patient=wrong),item_code='MED',quantity=10)
    with pytest.raises(ValidationError):add_item(basket.pk,s.u,2,'MED',1,pi.pk)


def test_ui_catalog_basket_review_and_no_get_mutation(catalog):
    s=catalog
    response=s.client.get(reverse('pharmacy-catalog'));assert response.status_code==200
    assert s.client.get(reverse('pharmacy-catalog-detail',args=[s.i.pk])).status_code==200
    assert s.client.post(reverse('pharmacy-catalog-detail',args=[s.i.pk]),{'action':'profile'}).status_code==403
    response=s.client.post(reverse('pharmacy-baskets'),{'patient':s.p.pk});assert response.status_code==302
    basket=DispensingBasket.objects.get()
    url=reverse('pharmacy-basket',args=[basket.pk])
    assert s.client.post(url,{'code':'MED','packs':1,'prescription_item':s.pi.pk,'revision':1}).status_code==302
    action=reverse('pharmacy-basket-action',args=[basket.pk])
    assert s.client.get(action).status_code==405
    assert s.client.post(action,{'action':'checkout','revision':2,'checkout_key':basket.checkout_key}).status_code==302
    assert not Dispense.objects.exists()
    response=s.client.post(action,{'action':'checkout','revision':2,'checkout_key':basket.checkout_key,'reviewed':'on'},follow=True)
    assert response.status_code==200 and Dispense.objects.count()==1
    assert b'Invoice #' in response.content


def test_invalid_barcode_quantity_missing_price_and_review(catalog):
    s=catalog;basket=create_basket(s.p.pk,s.u)
    with pytest.raises(ValidationError):add_item(basket.pk,s.u,1,'UNKNOWN',1,s.pi.pk)
    for quantity in ['NaN','-1','0','0.001','100000000']:
        with pytest.raises(ValidationError):add_item(basket.pk,s.u,1,'MED',quantity,s.pi.pk)
    PriceListItem.objects.all().delete()
    with pytest.raises(ValidationError,match='price'):add_item(basket.pk,s.u,1,'MED',1,s.pi.pk)
    assert not BasketLine.objects.exists()
    MedicineProfile.objects.filter(item=s.i).update(reviewed=False)
    with pytest.raises(ValidationError,match='Review'):add_item(basket.pk,s.u,1,'MED',1,s.pi.pk)


def test_merge_relinks_basket_and_rejects_late_direct_writes(catalog):
    from apps.operations.advanced_services import merge_patients
    s=catalog;basket=prepared(s)
    target=Patient.objects.create(first_name='Canonical',last_name='Patient',gender='F',facility=s.f)
    review=DuplicateReview.objects.create(patient=target,candidate=s.p,status='confirmed',created_by=s.u)
    merge_patients(review.pk,s.u,'Verified test identity')
    basket.refresh_from_db();assert basket.patient_id==target.pk
    checkout(basket.pk,s.u,basket.revision,basket.checkout_key)
    with pytest.raises(IntegrityError),transaction.atomic():
        DispensingBasket.objects.bulk_create([DispensingBasket(patient=s.p,created_by=s.u)])


def test_failure_after_first_allocation_rolls_back_stock_rx_and_invoice(catalog,monkeypatch):
    s=catalog;s.b.quantity_on_hand=1;s.b.save()
    Batch.objects.create(item=s.i,location=s.l,quantity_on_hand=4,expiry=s.b.expiry+timedelta(days=1))
    basket=prepared(s)
    original=Dispense.save
    calls=[]
    def fail_second(instance,*args,**kwargs):
        calls.append(instance.batch_id)
        if len(calls)==2:raise ValidationError('Synthetic downstream failure')
        return original(instance,*args,**kwargs)
    monkeypatch.setattr(Dispense,'save',fail_second)
    with pytest.raises(ValidationError,match='downstream'):checkout(basket.pk,s.u,2,basket.checkout_key)
    assert len(calls)==2
    s.b.refresh_from_db();s.pi.refresh_from_db();basket.refresh_from_db()
    assert s.b.quantity_on_hand==1 and s.pi.dispensed_quantity==0 and basket.status=='open'
    assert not Dispense.objects.exists() and not Invoice.objects.exists() and not BasketAllocation.objects.exists()
    assert not StockMovement.objects.filter(reason='dispense').exists()


def test_barcode_cannot_map_other_medicine_package_or_ambiguous_code(catalog):
    from apps.pharmacy.checkout_services import resolve_scan
    s=catalog;other=InventoryItem.objects.create(code='OTHER',name='Other')
    pack=PackageUnit.objects.create(item=other,name='Other pack',units_per_pack=10)
    with pytest.raises(ValidationError):MedicineBarcode(code='SCAN',item=s.i,package=pack).full_clean()
    with pytest.raises(ValidationError):MedicineBarcode(code='OTHER',item=s.i).full_clean()
    MedicineBarcode.objects.create(code='FUTURE',item=s.i)
    InventoryItem.objects.create(code='FUTURE',name='Later collision')
    with pytest.raises(ValidationError,match='Ambiguous'):resolve_scan('FUTURE')
