from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from .models import GoodsReceipt, GoodsReceiptLine, Batch, StockMovement, PurchaseOrder, InventoryItem

@transaction.atomic
def post_goods_receipt(receipt_id):
    grn = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    if grn.posted:
        return grn
    if not grn.location_id:
        raise ValidationError('Select a receiving stock location before posting.')
    po = PurchaseOrder.objects.select_for_update().get(pk=grn.po_id)
    if po.status != PurchaseOrder.APPROVED:
        raise ValidationError('Only approved purchase orders may receive stock.')
    lines = list(grn.lines.order_by('item_id', 'pk'))
    if not lines:
        raise ValidationError('Add receipt lines before posting.')
    for line in lines:
        if line.quantity_received <= 0:
            raise ValidationError('Received quantity must be positive.')
        if line.po_line_id and (line.po_line.po_id != po.pk or line.po_line.item_id != line.item_id):
            raise ValidationError('Receipt line does not match the purchase order.')
        InventoryItem.objects.select_for_update().get(pk=line.item_id)
        batch = Batch.objects.select_for_update().filter(item=line.item, batch_no=line.batch_no, expiry=line.expiry, location=grn.location).first()
        if batch is None:
            batch = Batch.objects.create(item=line.item, batch_no=line.batch_no, expiry=line.expiry, location=grn.location)
        batch.quantity_on_hand += line.quantity_received
        batch.save(update_fields=['quantity_on_hand'])
        StockMovement.objects.create(item=line.item, batch=batch, direction='in', quantity=line.quantity_received, reason='GRN', ref=f'GRN:{grn.pk}')
    grn.posted = True
    grn.save(update_fields=['posted'])
    if all((GoodsReceiptLine.objects.filter(grn__po=po, grn__posted=True, po_line=pl).aggregate(s=Sum('quantity_received'))['s'] or 0) >= pl.quantity_ordered for pl in po.lines.all()):
        po.status = PurchaseOrder.RECEIVED
        po.save(update_fields=['status'])
    return grn
