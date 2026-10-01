from apps.accounts.approval_services import require as require_approval
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
    if po.facility_id and grn.location.facility_id != po.facility_id:
        raise ValidationError('Receiving location must belong to the purchase order facility.')
    if po.status != PurchaseOrder.APPROVED:
        raise ValidationError('Only approved purchase orders may receive stock.')
    lines = list(grn.lines.order_by('item_id', 'pk'))
    if not lines:
        raise ValidationError('Add receipt lines before posting.')
    incoming={}
    for line in lines:
        if not line.po_line_id or line.po_line.po_id!=po.pk or line.po_line.item_id!=line.item_id:
            raise ValidationError('Every receipt line must match an approved purchase order line.')
        incoming[line.po_line_id]=incoming.get(line.po_line_id,0)+line.quantity_received
    for line_id,quantity in incoming.items():
        from .models import PurchaseOrderLine
        ordered=PurchaseOrderLine.objects.get(pk=line_id).quantity_ordered
        received=GoodsReceiptLine.objects.filter(po_line_id=line_id,grn__posted=True).aggregate(s=Sum('quantity_received'))['s'] or 0
        if quantity+received>ordered:raise ValidationError('Receipt exceeds the approved order. Obtain a separate approved order for extra stock.')
    for line in lines:
        if not line.quantity_received.is_finite() or line.quantity_received <= 0:
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


@transaction.atomic
def approve_purchase_order(pk,actor):
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone
    from common.facility_scope import filter_by_facility
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','manager')):raise PermissionDenied
    po=filter_by_facility(PurchaseOrder.objects.select_for_update(),actor).filter(pk=pk).first()
    if not po:raise PermissionDenied
    if po.status==PurchaseOrder.APPROVED:return po
    if po.status!=PurchaseOrder.DRAFT:raise ValidationError('Only draft orders may be approved.')
    if not po.created_by_id:raise ValidationError('A staff member must claim this legacy draft before approval.')
    if po.created_by_id==actor.pk:raise ValidationError('A different supervisor must approve this purchase order.')
    lines=list(po.lines.all())
    if not lines or any(l.quantity_ordered<=0 or l.unit_cost<0 for l in lines):raise ValidationError('Add valid order lines before approval.')
    require_approval(actor,po.facility_id,'purchase',sum((l.quantity_ordered*l.unit_cost for l in lines),start=0))
    po.status=PurchaseOrder.APPROVED;po.approved_by=actor;po.approved_at=timezone.now();po._history_user=actor;po.save()
    return po
