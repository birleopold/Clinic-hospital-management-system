"""Read-only drill-downs using original financial and stock records."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from django.db.models import Sum, F, Q
from django.utils import timezone
from apps.billing.models import Invoice, CashSession
from apps.billing.payment_services import net_paid
from apps.inventory.models import InventoryItem, Batch, StockMovement, PurchaseOrderLine, GoodsReceiptLine
from apps.pharmacy.models import Dispense
from apps.pharmacy.services import usable_batches
from .models import Refund, ReplenishmentRule, MedicineReturn


def invoice_reconciliation(invoice):
    lines=invoice.lines.aggregate(s=Sum('line_total'))['s'] or Decimal('0')
    payments=net_paid(invoice)
    return {'line_total':lines,'net_paid':payments,'total_difference':invoice.total_amount-lines,'paid_difference':invoice.paid_amount-payments}


def session_reconciliation(session):
    payments=session.payments.filter(method='cash').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    refunds=Refund.objects.filter(cash_session=session,status='approved').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    expected=session.opening_float+payments-refunds
    return {'payments':payments,'refunds':refunds,'expected':expected,'difference':session.expected_cash-expected,'counted_difference':None if session.counted_cash is None else session.counted_cash-expected}


def dispense_reconciliation(dispense):
    from apps.billing.models import InvoiceLine
    quantity=StockMovement.objects.filter(ref=f'dispense:{dispense.pk}',direction='out',reason='dispense').aggregate(s=Sum('quantity'))['s'] or Decimal('0')
    line=InvoiceLine.objects.filter(source_ref=f'dispense:{dispense.pk}').first()
    returns=[]
    for returned in dispense.returns.filter(status='posted').select_related('credit_line','returned_batch'):
        movements=StockMovement.objects.filter(ref=f'return:{returned.pk}')
        received=movements.filter(direction='in').aggregate(s=Sum('quantity'))['s'] or Decimal('0')
        disposed=movements.filter(direction='out').aggregate(s=Sum('quantity'))['s'] or Decimal('0')
        returns.append({'record':returned,'stock_difference':received-disposed-(0 if returned.disposition=='dispose' else returned.quantity),'credit_difference':returned.amount+(returned.credit_line.line_total if returned.credit_line else 0)})
    return {'stock_difference':quantity-dispense.quantity,'billing_quantity_difference':None if line is None else line.quantity-dispense.quantity,'line':line,'returns':returns}


def replenishment_rows(facility,items):
    ids=[i.pk for i in items];since=timezone.now()-timedelta(days=30)
    usable=list(usable_batches().filter(location__facility=facility,item_id__in=ids).select_related('location','item'))
    rules={r.item_id:r for r in ReplenishmentRule.objects.filter(facility=facility,item_id__in=ids).select_related('preferred_location')}
    consumed={r['item_id']:r['total'] for r in StockMovement.objects.filter(batch__location__facility=facility,item_id__in=ids,direction='out',reason__in=['dispense','vaccination'],created_at__gte=since).values('item_id').annotate(total=Sum('quantity'))}
    pending={};po_lines=list(PurchaseOrderLine.objects.filter(po__facility=facility,po__status='approved',item_id__in=ids).select_related('po'))
    received={r['po_line_id']:r['total'] for r in GoodsReceiptLine.objects.filter(po_line_id__in=[p.pk for p in po_lines],grn__posted=True).values('po_line_id').annotate(total=Sum('quantity_received'))}
    for line in po_lines:pending[line.item_id]=pending.get(line.item_id,Decimal('0'))+max(Decimal('0'),line.quantity_ordered-received.get(line.pk,Decimal('0')))
    result=[]
    for item in items:
        rule=rules.get(item.pk);lead=rule.lead_days if rule else 7;review=rule.review_days if rule else 7;safety=rule.safety_days if rule else 7
        daily=consumed.get(item.pk,Decimal('0'))/30
        target=max(item.reorder_level,(daily*(lead+review+safety)).quantize(Decimal('1'),rounding=ROUND_CEILING))
        batches=[b for b in usable if b.item_id==item.pk]
        stock=sum((b.quantity_on_hand for b in batches),Decimal('0'));open_po=pending.get(item.pk,Decimal('0'))
        transfers=[]
        if rule and rule.preferred_location_id:
            destination_stock=sum((b.quantity_on_hand for b in batches if b.location_id==rule.preferred_location_id),Decimal('0'))
            need=max(Decimal('0'),target-destination_stock)
            for batch in batches:
                if batch.location_id==rule.preferred_location_id or need<=0:continue
                qty=min(need,batch.quantity_on_hand)
                transfers.append({'batch':batch,'destination':rule.preferred_location,'quantity':qty});need-=qty
        result.append({'item':item,'usable':stock,'consumed':consumed.get(item.pk,0),'daily':daily.quantize(Decimal('.01')),'lead':lead,'review':review,'safety':safety,'target':target,'open_po':open_po,'suggested':max(Decimal('0'),target-stock-open_po),'transfers':transfers,'rule':rule})
    return result
