"""Basket commands: patient lock first, immutable completion, no implicit payment."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.demographics.models import Patient
from apps.inventory.models import InventoryItem, Batch
from apps.billing.models import Invoice, InvoiceLine, PriceListItem
from apps.billing.services import price_for, get_active_pricelist, recalc_invoice
from common.facility_scope import filter_by_patient_facility, filter_by_facility
from .models import (MedicineProfile, MedicineBarcode, PharmacyPolicy, DispensingBasket,
                     BasketLine, BasketAllocation, PrescriptionItem, Dispense)
from .services import usable_batches


def require_dispenser(actor):
    if not actor.is_authenticated or not (actor.is_superuser or actor.role in ('admin','pharmacy')):
        raise PermissionDenied


def policy_check(patient, profile, prescription_item):
    if not profile.active or not profile.reviewed:
        raise ValidationError('Review and activate the medicine catalog entry before dispensing.')
    if not prescription_item:
        if profile.prescription_required:
            raise ValidationError('This medicine requires a prescription line.')
        if not PharmacyPolicy.objects.filter(facility_id=patient.facility_id, allow_retail=True).exists():
            raise ValidationError('Non-prescription sales are not enabled for this facility.')


def medicine_snapshot(item, profile):
    return {key: str(getattr(profile,key)) for key in ('generic_name','ingredients','strength','dosage_form','route','brand')} | {'code':item.code,'name':item.name,'uom':item.uom}


def rx_snapshot(pi):
    return {key:str(getattr(pi,key)) for key in ('dose','frequency','duration','notes')} if pi else {}


def resolve_scan(code):
    code=code.strip()
    alias=MedicineBarcode.objects.select_related('item','package').filter(code=code,active=True).first()
    item=InventoryItem.objects.filter(code=code).first()
    if alias and item and (alias.item_id!=item.pk or alias.package_id):
        raise ValidationError('Ambiguous barcode/catalog code. Ask the catalog administrator to correct it.')
    if alias:
        if alias.package_id and alias.package.item_id!=alias.item_id:
            raise ValidationError('Barcode package no longer matches its medicine.')
        return alias.item,alias.package
    if item:return item,None
    raise ValidationError('Unknown code. Search the catalog or ask an administrator to add its barcode.')


def locked_basket(pk, actor, revision=None):
    require_dispenser(actor)
    initial=filter_by_patient_facility(DispensingBasket.objects.all(),actor).filter(pk=pk).first()
    if not initial:raise PermissionDenied
    patient=Patient.objects.select_for_update().get(pk=initial.patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed. Reload the canonical chart.')
    basket=DispensingBasket.objects.select_for_update().get(pk=pk)
    if basket.patient_id!=patient.pk:raise ValidationError('Patient identity changed. Reload this basket.')
    basket.patient=patient
    if revision is not None and basket.revision!=revision:
        raise ValidationError('This basket changed. Reload before trying again.')
    return basket


def save_basket(basket,actor):
    basket.revision+=1
    basket._history_user=actor
    basket.save()


@transaction.atomic
def create_basket(patient_id,actor):
    require_dispenser(actor)
    patient=filter_by_facility(Patient.objects.select_for_update(),actor).filter(pk=patient_id,merged_into__isnull=True).first()
    if not patient:raise PermissionDenied
    if not patient.facility_id:raise ValidationError('Assign the patient to a facility first.')
    basket=DispensingBasket(patient=patient,created_by=actor)
    basket._history_user=actor;basket.save()
    return basket


@transaction.atomic
def add_item(pk,actor,revision,code,packs,prescription_item_id=None,instructions=''):
    basket=locked_basket(pk,actor,revision)
    if basket.status!='open':raise ValidationError('Resume the open basket before adding items.')
    if basket.lines.filter(removed=False).count()>=50:raise ValidationError('Use at most 50 lines per basket.')
    item,package=resolve_scan(code)
    profile=MedicineProfile.objects.filter(item=item).first()
    if not profile:raise ValidationError('Add and review this medicine in the catalog first.')
    try: packs=Decimal(str(packs))
    except InvalidOperation:raise ValidationError('Enter a valid package quantity.')
    factor=package.units_per_pack if package else Decimal('1')
    quantity=packs*factor
    if not packs.is_finite() or not quantity.is_finite() or quantity<=0 or quantity>Decimal('99999999.99') or quantity!=quantity.quantize(Decimal('.01')) or packs>Decimal('99999999.99') or packs!=packs.quantize(Decimal('.01')):
        raise ValidationError('Quantity must be positive and expressible in base units to two decimal places.')
    pi=None
    if prescription_item_id:
        pi=PrescriptionItem.objects.filter(pk=prescription_item_id,prescription__patient=basket.patient,item_code=item.code).first()
        if not pi:raise ValidationError('Choose this patient’s matching prescription line.')
        requested=sum(basket.lines.filter(removed=False,prescription_item=pi).values_list('quantity',flat=True),Decimal('0'))
        if requested+quantity>pi.quantity-pi.dispensed_quantity:raise ValidationError('Basket exceeds the outstanding prescription quantity.')
    policy_check(basket.patient,profile,pi)
    price=price_for(item.code)
    if price is None or price<0:raise ValidationError('Configure a non-negative active price before adding this item.')
    line=BasketLine(basket=basket,item=item,prescription_item=pi,package=package,package_name=package.name if package else 'Base units',units_per_pack=factor,packs=packs,quantity=quantity,unit_price=price,medicine_snapshot=medicine_snapshot(item,profile),prescription_snapshot=rx_snapshot(pi),instructions=instructions.strip())
    line.full_clean();line._history_user=actor;line.save();save_basket(basket,actor)
    return line


@transaction.atomic
def change_basket(pk,actor,revision,action,line_id=None):
    basket=locked_basket(pk,actor,revision)
    if basket.status in ('completed','cancelled'):raise ValidationError('This basket is closed.')
    if action=='remove' and basket.status=='open':
        line=basket.lines.filter(pk=line_id,removed=False).first()
        if not line:raise ValidationError('Line not found in this basket.')
        line.removed=True;line._history_user=actor;line.save(update_fields=['removed'])
    elif action=='hold' and basket.status=='open':basket.status='held'
    elif action=='resume' and basket.status=='held':basket.status='open'
    elif action=='cancel':basket.status='cancelled'
    else:raise ValidationError('Invalid basket action.')
    save_basket(basket,actor);return basket


@transaction.atomic
def checkout(pk,actor,revision,key):
    basket=locked_basket(pk,actor)
    if str(basket.checkout_key)!=str(key):raise ValidationError('Checkout reference does not match this basket.')
    # Replays return the original result without touching stock or invoicing.
    if basket.status=='completed':return basket
    if basket.revision!=revision:raise ValidationError('Basket changed. Reload and review before dispensing.')
    if basket.status!='open':raise ValidationError('Only an open basket can be dispensed.')
    lines=list(basket.lines.filter(removed=False).select_related('item','package').order_by('item_id','pk'))
    if not lines:raise ValidationError('Add at least one medicine.')
    item_ids=sorted({line.item_id for line in lines})
    items={i.pk:i for i in InventoryItem.objects.select_for_update().filter(pk__in=item_ids).order_by('pk')}
    profiles={p.item_id:p for p in MedicineProfile.objects.select_for_update().filter(item_id__in=item_ids).order_by('item_id')}
    pis={p.pk:p for p in PrescriptionItem.objects.select_for_update().filter(pk__in=[l.prescription_item_id for l in lines if l.prescription_item_id]).order_by('pk')}
    pricelist=get_active_pricelist()
    prices={p.code:p.amount for p in PriceListItem.objects.select_for_update().filter(pricelist=pricelist,code__in=[i.code for i in items.values()],active=True).order_by('pk')}
    required={};rx_required={}
    for line in lines:
        item=items[line.item_id];profile=profiles.get(line.item_id);pi=pis.get(line.prescription_item_id)
        if not profile:raise ValidationError('Catalog entry missing.')
        policy_check(basket.patient,profile,pi)
        if medicine_snapshot(item,profile)!=line.medicine_snapshot or prices.get(item.code)!=line.unit_price:
            raise ValidationError(f'{item.code}: catalog or price changed. Remove and re-add this line to review it.')
        if line.package_id and (line.package.item_id!=item.pk or line.package.units_per_pack!=line.units_per_pack or line.package.name!=line.package_name):
            raise ValidationError('Package conversion changed. Remove and re-add this line.')
        if pi and (pi.prescription.patient_id!=basket.patient_id or pi.item_code!=item.code or rx_snapshot(pi)!=line.prescription_snapshot):
            raise ValidationError('Prescription changed. Remove and re-add this line.')
        required[item.pk]=required.get(item.pk,Decimal('0'))+line.quantity
        if pi:rx_required[pi.pk]=rx_required.get(pi.pk,Decimal('0'))+line.quantity
    for pi_id,qty in rx_required.items():
        if qty>pis[pi_id].quantity-pis[pi_id].dispensed_quantity:raise ValidationError('Prescription quantity was dispensed elsewhere. Review the basket.')
    # Lock in stable primary-key order, then allocate earliest expiry first.
    batches=list(usable_batches().select_for_update(of=('self',)).filter(item_id__in=item_ids,location__facility_id=basket.patient.facility_id).order_by('pk'))
    batches.sort(key=lambda b:(b.expiry is None,b.expiry or timezone.localdate(),b.pk))
    remaining={b.pk:b.quantity_on_hand for b in batches}
    for iid,qty in required.items():
        if sum((b.quantity_on_hand for b in batches if b.item_id==iid),Decimal('0'))<qty:
            raise ValidationError(f'{items[iid].code}: insufficient usable stock. Nothing has been dispensed.')
    if sum((l.total for l in lines),Decimal('0'))>Decimal('9999999998.00'):
        raise ValidationError('Invoice total exceeds supported size.')
    basket.invoice=Invoice.objects.create(patient=basket.patient)
    # Existing dispense service performs stock movements, Rx progress and billing.
    # Its optional internal invoice/price context keeps one dedicated basket invoice.
    for line in lines:
        outstanding=line.quantity
        for batch in batches:
            if batch.item_id!=line.item_id or remaining[batch.pk]<=0:continue
            qty=min(outstanding,remaining[batch.pk])
            if not qty:continue
            dispense=Dispense(patient=basket.patient,prescription_item=pis.get(line.prescription_item_id),batch=batch,item_code=items[line.item_id].code,item_name=line.medicine_snapshot['name'],quantity=qty,notes=line.instructions)
            dispense._billing_invoice=basket.invoice;dispense._billing_unit_price=line.unit_price
            dispense._history_user=actor;dispense.save()
            allocation=BasketAllocation(line=line,dispense=dispense);allocation._history_user=actor;allocation.save()
            remaining[batch.pk]-=qty;outstanding-=qty
            if not outstanding:break
    recalc_invoice(basket.invoice)
    if basket.invoice.total_amount>Decimal('9999999999.99'):raise ValidationError('Invoice total exceeds supported size.')
    basket.invoice.status=Invoice.READY if basket.invoice.total_amount>0 else Invoice.PAID
    basket.invoice.save(update_fields=['status'])
    basket.status='completed';basket.completed_at=timezone.now();basket.completed_by=actor
    save_basket(basket,actor)
    return basket
