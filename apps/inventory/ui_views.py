from common.facility_scope import filter_by_facility, user_staff_facility_id
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden, HttpResponse
from django.db.models import Sum
from django.utils import timezone
from datetime import datetime
from decimal import Decimal, InvalidOperation
import csv
import io
import re
from django.urls import reverse

from .models import (
    InventoryItem, Batch, StockMovement,
    Supplier, PurchaseOrder, PurchaseOrderLine,
    GoodsReceipt, GoodsReceiptLine,
)
from apps.pharmacy.models import Backorder, Dispense, PrescriptionItem


@login_required
def stock_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy','store','manager')):
        return HttpResponseForbidden('Not allowed')
    items = (
        InventoryItem.objects
        .annotate(qoh=Sum('batches__quantity_on_hand', filter=Q() if user.is_superuser else Q(batches__location__facility_id=user_staff_facility_id(user) or -1)))
        .order_by('code')[:500]
    )
    context = { 'items': items }
    return render(request, 'inventory/stock.html', context)


@login_required
def movements_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','pharmacy','store','manager')):
        return HttpResponseForbidden('Not allowed')
    moves = filter_by_facility(StockMovement.objects.all(), user, field='batch__location__facility_id').select_related('item','batch').order_by('-created_at')[:200]
    context = { 'movements': moves }
    return render(request, 'inventory/movements.html', context)


# Items: create/edit
@login_required
def item_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip().upper()
        name = (request.POST.get('name') or '').strip()
        uom = (request.POST.get('uom') or '').strip() or 'unit'
        from decimal import Decimal as _D
        rl = request.POST.get('reorder_level') or '0'
        try:
            reorder_level = _D(rl)
        except Exception:
            reorder_level = _D('0')
        if not code or not name:
            # re-render with error
            return render(request, 'inventory/item_form.html', {'item': None, 'mode': 'create', 'error': 'Code and Name are required.'})
        if InventoryItem.objects.filter(code=code).exists():
            return render(request, 'inventory/item_form.html', {'item': None, 'mode': 'create', 'error': 'Item code already exists.'})
        InventoryItem.objects.create(code=code, name=name, uom=uom, reorder_level=reorder_level)
        if request.headers.get('HX-Request'):
            resp = HttpResponse(status=204)
            resp['HX-Redirect'] = reverse('inventory-stock')
            return resp
        return redirect('inventory-stock')
    return render(request, 'inventory/item_form.html', {'item': None, 'mode': 'create'})


@login_required
def item_edit_view(request, item_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    it = get_object_or_404(InventoryItem, pk=item_id)
    # Inline partial form for HTMX
    if request.method == 'GET' and (request.headers.get('HX-Request') or request.GET.get('partial') == '1'):
        return render(request, 'inventory/_item_inline_form.html', {'item': it})
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip().upper()
        name = (request.POST.get('name') or '').strip()
        uom = (request.POST.get('uom') or '').strip() or 'unit'
        from decimal import Decimal as _D
        rl = request.POST.get('reorder_level') or str(it.reorder_level or '0')
        try:
            reorder_level = _D(rl)
        except Exception:
            reorder_level = it.reorder_level
        if not code or not name:
            if request.headers.get('HX-Request') or request.POST.get('partial') == '1':
                return render(request, 'inventory/_item_inline_form.html', {'item': it, 'error': 'Code and Name are required.'})
            return render(request, 'inventory/item_form.html', {'item': it, 'mode': 'edit', 'error': 'Code and Name are required.'})
        # uniqueness on code
        if InventoryItem.objects.exclude(pk=it.pk).filter(code=code).exists():
            if request.headers.get('HX-Request') or request.POST.get('partial') == '1':
                return render(request, 'inventory/_item_inline_form.html', {'item': it, 'error': 'Another item with this code exists.'})
            return render(request, 'inventory/item_form.html', {'item': it, 'mode': 'edit', 'error': 'Another item with this code exists.'})
        it.code = code
        it.name = name
        it.uom = uom
        it.reorder_level = reorder_level
        it.save()
        if request.headers.get('HX-Request'):
            resp = HttpResponse(status=204)
            resp['HX-Redirect'] = reverse('inventory-stock')
            return resp
        return redirect('inventory-stock')
    return render(request, 'inventory/item_form.html', {'item': it, 'mode': 'edit'})


@login_required
def batch_create_view(request, item_id: int):
    return redirect('suite-stock')


@login_required
def item_adjust_view(request, item_id: int):
    return redirect('suite-collection', slug='counts')

# Procurement: Suppliers
@login_required
def suppliers_list_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    q = (request.GET.get('q') or '').strip()
    qs = Supplier.objects.all().order_by('name')
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    return render(request, 'inventory/suppliers_list.html', {'suppliers': qs[:500], 'q': q})


@login_required
def supplier_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    if request.method == 'POST':
        Supplier.objects.create(
            name=(request.POST.get('name') or '').strip(),
            phone=(request.POST.get('phone') or '').strip(),
            email=(request.POST.get('email') or '').strip(),
            address=(request.POST.get('address') or '').strip(),
            contact_person=(request.POST.get('contact_person') or '').strip(),
            notes=(request.POST.get('notes') or '').strip(),
        )
        return redirect('inventory-suppliers')
    return render(request, 'inventory/supplier_form.html', {'supplier': None, 'mode': 'create'})


@login_required
def supplier_edit_view(request, supplier_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    s = get_object_or_404(Supplier, pk=supplier_id)
    if request.method == 'POST':
        s.name = (request.POST.get('name') or '').strip()
        s.phone = (request.POST.get('phone') or '').strip()
        s.email = (request.POST.get('email') or '').strip()
        s.address = (request.POST.get('address') or '').strip()
        s.contact_person = (request.POST.get('contact_person') or '').strip()
        s.notes = (request.POST.get('notes') or '').strip()
        s.save()
        return redirect('inventory-suppliers')
    return render(request, 'inventory/supplier_form.html', {'supplier': s, 'mode': 'edit'})


# Procurement: Purchase Orders
@login_required
def po_list_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    status_f = request.GET.get('status')
    qs = filter_by_facility(PurchaseOrder.objects.all(), user).select_related('supplier').order_by('-id')
    if status_f:
        qs = qs.filter(status=status_f)
    pos = list(qs[:200])
    # Compute received percentage per PO for display
    if pos:
        from collections import defaultdict
        po_ids = [p.id for p in pos]
        ordered_by_po = defaultdict(Decimal)
        for row in (
            PurchaseOrderLine.objects
            .filter(po_id__in=po_ids)
            .values('po_id')
            .annotate(s=Sum('quantity_ordered'))
        ):
            ordered_by_po[row['po_id']] = row['s'] or Decimal('0')
        received_by_po = defaultdict(Decimal)
        for row in (
            GoodsReceiptLine.objects
            .filter(grn__po_id__in=po_ids)
            .values('grn__po_id')
            .annotate(s=Sum('quantity_received'))
        ):
            received_by_po[row['grn__po_id']] = row['s'] or Decimal('0')
        for p in pos:
            ordered = ordered_by_po.get(p.id, Decimal('0'))
            received = received_by_po.get(p.id, Decimal('0'))
            pct = Decimal('0')
            if ordered and ordered > 0:
                try:
                    pct = (received / ordered) * 100
                except Exception:
                    pct = Decimal('0')
            setattr(p, 'received_pct', pct)
            # Add textual indicator
            if p.status in (PurchaseOrder.DRAFT, PurchaseOrder.CANCELLED):
                setattr(p, 'recv_state', p.status)
            else:
                if pct >= 99.999:
                    setattr(p, 'recv_state', 'received')
                elif pct > 0:
                    setattr(p, 'recv_state', 'partial')
                else:
                    setattr(p, 'recv_state', 'approved')
    return render(request, 'inventory/po_list.html', {'pos': pos, 'status': status_f})


@login_required
def po_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    if request.method == 'POST':
        sid = int(request.POST.get('supplier') or '0')
        supplier = get_object_or_404(Supplier, pk=sid)
        po = PurchaseOrder.objects.create(facility_id=user_staff_facility_id(user), supplier=supplier, remarks=(request.POST.get('remarks') or '').strip())
        return redirect('inventory-po-edit', po_id=po.id)
    suppliers = Supplier.objects.all().order_by('name')
    return render(request, 'inventory/po_form.html', {'po': None, 'suppliers': suppliers, 'items': [], 'mode': 'create'})


@login_required
def po_edit_view(request, po_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user).select_related('supplier'), pk=po_id)
    items = InventoryItem.objects.all().order_by('code')[:500]
    if request.method == 'POST' and po.status == PurchaseOrder.DRAFT:
        try:
            item_id = int(request.POST.get('item') or '0')
            if item_id <= 0:
                raise ValueError('Select an inventory item.')
            qty_raw = (request.POST.get('quantity_ordered') or '').strip()
            cost_raw = (request.POST.get('unit_cost') or '').strip()
            item = get_object_or_404(InventoryItem, pk=item_id)
            quantity_ordered = Decimal(qty_raw or '0')
            unit_cost = Decimal(cost_raw or '0')
            if quantity_ordered <= 0:
                raise ValueError('Quantity must be greater than zero.')
            if unit_cost < 0:
                raise ValueError('Unit cost cannot be negative.')
            PurchaseOrderLine.objects.create(
                po=po, item=item, quantity_ordered=quantity_ordered, unit_cost=unit_cost
            )
            messages.success(request, 'Line added to purchase order.')
        except (ValueError, TypeError, InvalidOperation) as e:
            messages.error(request, str(e) if str(e) else 'Invalid quantity or cost.')
        return redirect('inventory-po-edit', po_id=po.id)
    lines = list(po.lines.select_related('item').all())
    # Compute received qty per line (prefer po_line), fallback to per-item
    rec_by_line = {}
    for row in (
        GoodsReceiptLine.objects
        .filter(grn__po=po, po_line__isnull=False)
        .values('po_line_id')
        .annotate(s=Sum('quantity_received'))
    ):
        rec_by_line[row['po_line_id']] = row['s'] or Decimal('0')
    rec_by_item = {}
    for row in (
        GoodsReceiptLine.objects
        .filter(grn__po=po)
        .values('item_id')
        .annotate(s=Sum('quantity_received'))
    ):
        rec_by_item[row['item_id']] = row['s'] or Decimal('0')
    is_fully_received = True
    ordered_total = Decimal('0')
    received_total = Decimal('0')
    outstanding_total = Decimal('0')
    over_total = Decimal('0')
    for ln in lines:
        recd = rec_by_line.get(ln.id)
        if recd is None:
            recd = rec_by_item.get(ln.item_id, Decimal('0'))
        setattr(ln, 'received_qty', recd)
        try:
            outstanding = (ln.quantity_ordered or Decimal('0')) - (recd or Decimal('0'))
        except Exception:
            outstanding = Decimal('0')
        if outstanding < 0:
            outstanding = Decimal('0')
        setattr(ln, 'outstanding_qty', outstanding)
        # Over-receipt at line level (cumulative)
        try:
            over_qty = (recd or Decimal('0')) - (ln.quantity_ordered or Decimal('0'))
        except Exception:
            over_qty = Decimal('0')
        if over_qty < 0:
            over_qty = Decimal('0')
        setattr(ln, 'over_qty', over_qty)
        status = 'none'
        try:
            if recd >= ln.quantity_ordered:
                status = 'full'
            elif recd > 0:
                status = 'partial'
        except Exception:
            status = 'none'
        setattr(ln, 'receive_status', status)
        if outstanding > 0:
            is_fully_received = False
        ordered_total += (ln.quantity_ordered or Decimal('0'))
        received_total += (recd or Decimal('0'))
        outstanding_total += outstanding
        over_total += over_qty
    return render(request, 'inventory/po_form.html', {
        'po': po,
        'suppliers': [],
        'items': items,
        'lines': lines,
        'mode': 'edit',
        'is_fully_received': is_fully_received,
        'ordered_total': ordered_total,
        'received_total': received_total,
        'outstanding_total': outstanding_total,
        'over_total': over_total,
    })


@login_required
def po_line_update_view(request, po_id: int, line_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
    if po.status != PurchaseOrder.DRAFT:
        return HttpResponseForbidden('Cannot edit a non-draft PO')
    ln = get_object_or_404(PurchaseOrderLine, pk=line_id, po=po)
    # Sum received on this line (strict)
    rec_line = GoodsReceiptLine.objects.filter(po_line=ln).aggregate(s=Sum('quantity_received'))['s'] or Decimal('0')
    # Update only provided fields
    qty_raw = request.POST.get('quantity_ordered')
    cost_raw = request.POST.get('unit_cost')
    update_fields = []
    if qty_raw is not None:
        try:
            new_qty = Decimal(qty_raw)
        except Exception:
            return HttpResponseForbidden('Invalid quantity')
        if new_qty < rec_line:
            return HttpResponseForbidden(f'Cannot reduce quantity below already received ({rec_line}).')
        ln.quantity_ordered = new_qty
        update_fields.append('quantity_ordered')
    if cost_raw is not None:
        try:
            new_cost = Decimal(cost_raw)
        except Exception:
            return HttpResponseForbidden('Invalid unit cost')
        ln.unit_cost = new_cost
        update_fields.append('unit_cost')
    if update_fields:
        ln.save(update_fields=update_fields)
    if request.headers.get('HX-Request'):
        return HttpResponse('Line updated', status=200)
    return redirect('inventory-po-edit', po_id=po.id)


@login_required
def po_line_delete_view(request, po_id: int, line_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
    if po.status != PurchaseOrder.DRAFT:
        return HttpResponseForbidden('Cannot delete from a non-draft PO')
    ln = get_object_or_404(PurchaseOrderLine, pk=line_id, po=po)
    # Forbid delete if any GRN has referenced this line or received this item under this PO
    if GoodsReceiptLine.objects.filter(po_line=ln).exists() or GoodsReceiptLine.objects.filter(grn__po=po, item=ln.item).exists():
        return HttpResponseForbidden('Cannot delete a line that has receipts')
    ln.delete()
    if request.headers.get('HX-Request'):
        return HttpResponse('Line deleted', status=200)
    return redirect('inventory-po-edit', po_id=po.id)


@login_required
@require_POST
def po_approve_view(request, po_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
    if po.status == PurchaseOrder.DRAFT:
        po.status = PurchaseOrder.APPROVED
        po.save(update_fields=['status'])
    if request.headers.get('HX-Request'):
        return HttpResponse(status=204)
    return redirect('inventory-po-list')


@login_required
@require_POST
def po_close_view(request, po_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
    if po.status != PurchaseOrder.APPROVED:
        return HttpResponseForbidden('Only approved POs can be closed')
    # Fully received check: all lines received >= ordered
    lines = po.lines.all()
    if not lines.exists():
        return HttpResponseForbidden('No lines to close')
    rec_by_line = {
        row['po_line_id']: (row['s'] or Decimal('0'))
        for row in GoodsReceiptLine.objects.filter(grn__po=po, po_line__isnull=False).values('po_line_id').annotate(s=Sum('quantity_received'))
    }
    for ln in lines:
        recd = rec_by_line.get(ln.id, Decimal('0'))
        if recd < (ln.quantity_ordered or Decimal('0')):
            return HttpResponseForbidden('PO not fully received')
    po.status = PurchaseOrder.RECEIVED
    po.save(update_fields=['status'])
    if request.headers.get('HX-Request'):
        return HttpResponse(status=204)
    return redirect('inventory-po-list')


@login_required
@require_POST
def po_cancel_view(request, po_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
    if po.status in (PurchaseOrder.DRAFT, PurchaseOrder.APPROVED):
        po.status = PurchaseOrder.CANCELLED
        po.save(update_fields=['status'])
    if request.headers.get('HX-Request'):
        return HttpResponse(status=204)
    return redirect('inventory-po-list')


# Procurement: Goods Receipt (GRN)
@login_required
def grn_list_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    qs = filter_by_facility(GoodsReceipt.objects.all(), user, field='po__facility_id').select_related('po','po__supplier').order_by('-id')
    return render(request, 'inventory/grn_list.html', {'grns': qs[:200]})


@login_required
def grn_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    # Pick an approved PO to receive
    if request.method == 'POST':
        po_id = int(request.POST.get('po') or '0')
        po = get_object_or_404(filter_by_facility(PurchaseOrder.objects.all(), user), pk=po_id)
        grn = GoodsReceipt.objects.create(po=po, reference=(request.POST.get('reference') or '').strip())
        # capture lines arrays
        item_ids = request.POST.getlist('item')
        qtys = request.POST.getlist('qty')
        costs = request.POST.getlist('unit_cost')
        batches = request.POST.getlist('batch_no')
        expiries = request.POST.getlist('expiry')
        # Precompute received by PO line to allocate to outstanding first
        rec_by_line = {}
        for row in (
            GoodsReceiptLine.objects
            .filter(grn__po=po)
            .values('po_line_id')
            .annotate(s=Sum('quantity_received'))
        ):
            if row['po_line_id']:
                rec_by_line[row['po_line_id']] = row['s'] or 0
        for i in range(len(item_ids)):
            try:
                iid = int(item_ids[i])
                from decimal import Decimal as _D
                qty = _D(qtys[i])
                cost = costs[i]
                batch_no = (batches[i] if i < len(batches) else '').strip()
                expiry = (expiries[i] if i < len(expiries) else '').strip()
                item = get_object_or_404(InventoryItem, pk=iid)
                # choose a PO line with outstanding if multiple exist
                po_lines_for_item = list(po.lines.filter(item_id=iid).order_by('id'))
                po_line = None
                for pl in po_lines_for_item:
                    ordered = pl.quantity_ordered
                    received_so_far = rec_by_line.get(pl.id, 0)
                    try:
                        if received_so_far < ordered:
                            po_line = pl
                            break
                    except Exception:
                        continue
                if not po_line and po_lines_for_item:
                    po_line = po_lines_for_item[0]
                # Over-receipt guard with optional override
                if po_line and qty is not None:
                    try:
                        outstanding_line = (po_line.quantity_ordered or _D('0')) - _D(rec_by_line.get(po_line.id, 0) or 0)
                    except Exception:
                        outstanding_line = _D('0')
                    if outstanding_line < 0:
                        outstanding_line = _D('0')
                    if qty > outstanding_line:
                        allow = (request.POST.get('allow_overreceipt') == '1') and (request.user.is_superuser or request.user.role in ('admin','manager'))
                        reason = (request.POST.get('override_reason') or '').strip()
                        if not allow or not reason:
                            return HttpResponseForbidden(f'Over-receipt detected. Outstanding: {outstanding_line}, received: {qty}. Manager override with reason is required.')
                        # Persist reason by appending to GRN reference for audit trail
                        if grn.reference:
                            grn.reference = f"{grn.reference} | OVERRIDE: {reason}"
                        else:
                            grn.reference = f"OVERRIDE: {reason}"
                        grn.save(update_fields=['reference'])
                exp_date = None
                if expiry:
                    try:
                        exp_date = datetime.fromisoformat(expiry).date()
                    except Exception:
                        exp_date = None
                GoodsReceiptLine.objects.create(
                    grn=grn, po_line=po_line, item=item, batch_no=batch_no, expiry=exp_date,
                    quantity_received=qty, unit_cost=cost,
                )
            except Exception:
                continue
        if request.headers.get('HX-Request'):
            resp = HttpResponse(status=204)
            resp['HX-Redirect'] = reverse('inventory-grn-detail', kwargs={'grn_id': grn.id})
            return resp
        return redirect('inventory-grn-detail', grn_id=grn.id)
    approved_pos = filter_by_facility(PurchaseOrder.objects.all(), user).filter(status=PurchaseOrder.APPROVED).select_related('supplier').order_by('-id')[:200]
    items = InventoryItem.objects.all().order_by('code')[:500]
    return render(request, 'inventory/grn_form.html', {'approved_pos': approved_pos, 'items': items})


@login_required
def grn_detail_view(request, grn_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    grn = get_object_or_404(filter_by_facility(GoodsReceipt.objects.all(), user, field='po__facility_id').select_related('po','po__supplier'), pk=grn_id)
    lines = list(grn.lines.select_related('item','po_line').all())
    # Compute cumulative over-receipt variance per po_line within the PO
    rec_by_line = {
        row['po_line_id']: (row['s'] or Decimal('0'))
        for row in GoodsReceiptLine.objects.filter(grn__po=grn.po, po_line__isnull=False).values('po_line_id').annotate(s=Sum('quantity_received'))
    }
    for ln in lines:
        over = Decimal('0')
        try:
            if ln.po_line_id:
                total_rec = rec_by_line.get(ln.po_line_id, Decimal('0'))
                ordered = ln.po_line.quantity_ordered or Decimal('0')
                tmp = total_rec - ordered
                if tmp > 0:
                    over = tmp
        except Exception:
            over = Decimal('0')
        setattr(ln, 'over_received', over)
    from apps.operations.models import StockLocation
    context_locations = filter_by_facility(StockLocation.objects.all(), request.user)
    return render(request, 'inventory/grn_detail.html', {'grn': grn, 'lines': lines, 'locations': context_locations})


@login_required
@require_POST
def grn_post_view(request, grn_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    grn = get_object_or_404(filter_by_facility(GoodsReceipt.objects.all(), user, field='po__facility_id').select_related('po'), pk=grn_id)
    from .services import post_goods_receipt
    from django.core.exceptions import ValidationError
    from django.contrib import messages
    try:
        from apps.operations.models import StockLocation
        from django.db import transaction
        with transaction.atomic():
            grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
            if not grn.posted:
                location = get_object_or_404(filter_by_facility(StockLocation.objects.all(),user),pk=request.POST.get('location'))
                if grn.po.facility_id and grn.po.facility_id != location.facility_id:
                    raise ValidationError('Receiving location must match the purchase order facility.')
                grn.location = location
                grn.save(update_fields=['location'])
            elif not user.is_superuser and grn.location.facility_id != user_staff_facility_id(user):
                return HttpResponseForbidden('Not allowed')
            post_goods_receipt(grn.pk)
        messages.success(request, 'Receipt posted. Backorders remain pending patient handover.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('inventory-grn-detail', grn_id=grn.id)


# Inventory import (CSV/XLSX)
@login_required
def inventory_import_sample_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')
    sample = (
        'code,name,uom,reorder_level,batch_no,expiry,quantity,unit_cost\n'
        'AMOX500,Amoxicillin 500mg,capsule,50,B123,2027-12-31,100,2000\n'
        'PCM500,Paracetamol 500mg,tablet,100,B987,2026-06-30,250,1200\n'
    )
    resp = HttpResponse(sample, content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="inventory_import_sample.csv"'
    return resp


@login_required
def inventory_import_view(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Bulk legacy imports require a superuser. Use Stock control for facility stock.")
    user = request.user
    if not (user.is_superuser or user.role in ('admin','store','manager')):
        return HttpResponseForbidden('Not allowed')

    def norm(s: str) -> str:
        s = (s or '').strip().lower()
        s = re.sub(r'[^a-z0-9]+', ' ', s)
        return re.sub(r'\s+', ' ', s).strip()

    def parse_date(val):
        from datetime import date
        if not val:
            return None
        if isinstance(val, date):
            return val
        sval = str(val).strip()
        for fmt in ('%Y-%m-%d','%d/%m/%Y','%m/%d/%Y','%d-%m-%Y','%Y/%m/%d'):
            try:
                return datetime.strptime(sval, fmt).date()
            except Exception:
                continue
        return None

    def to_decimal(x, default=None):
        try:
            if x is None:
                return default
            if isinstance(x, (int, float, Decimal)):
                return Decimal(str(x))
            s = str(x).strip().replace(',', '')
            m = re.search(r'[-+]?\d+(?:\.\d+)?', s)
            if m:
                return Decimal(m.group(0))
            return default
        except Exception:
            return default

    result = None
    if request.method == 'POST':
        f = request.FILES.get('file')
        if not f:
            return HttpResponseForbidden('No file uploaded')
        filename = f.name.lower()
        rows = []
        headers = []
        # Read CSV
        if filename.endswith('.csv'):
            content = f.read().decode('utf-8-sig', errors='ignore')
            rdr = csv.reader(io.StringIO(content))
            for i, row in enumerate(rdr):
                if i == 0:
                    headers = [norm(h) for h in row]
                else:
                    rows.append(row)
        elif filename.endswith('.xlsx'):
            try:
                import openpyxl  # type: ignore
            except Exception:
                return HttpResponseForbidden('XLSX import requires openpyxl. Please upload CSV or install openpyxl.')
            wb = openpyxl.load_workbook(f, data_only=True)
            ws = wb.active
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [norm(str(h or '')) for h in row]
                else:
                    rows.append(list(row))
        else:
            return HttpResponseForbidden('Unsupported file type. Upload a .csv or .xlsx file.')

        # Map headers to canonical keys
        synonyms = {
            'code': ['code','sku','item code','itemcode','product code','product sku','stock item code','part no','part number','barcode','item id'],
            'name': ['name','item name','description','product name','stock item name'],
            'uom': ['uom','unit','unit name','measure','uom name'],
            'reorder_level': ['reorder level','reorderlevel','reorder','reorder point','re order point'],
            'batch_no': ['batch','batch no','batch number','lot','lot no','lot number'],
            'expiry': ['expiry','expiration','expire','expiry date','expiration date','exp date','exp'],
            'quantity': ['quantity on hand','quantity_on_hand','quantity','qty on hand','qtyonhand','qty','on hand','closing balance','closing qty','closing quantity'],
            'unit_cost': ['unit cost','cost','purchase cost','rate','buy rate','purchase rate'],
        }
        key_index = {}
        for canon, alts in synonyms.items():
            idx = None
            for j, h in enumerate(headers):
                if h in [norm(a) for a in alts + [canon]]:
                    idx = j
                    break
            if idx is not None:
                key_index[canon] = idx

        # Require at least code
        if 'code' not in key_index:
            return HttpResponseForbidden('File must include an item code column (e.g., code/SKU).')

        mode = request.POST.get('mode') or 'items_and_stock'
        replace_qoh = request.POST.get('replace_qoh') == '1'
        created_items = updated_items = 0
        created_batches = updated_batches = 0
        created_moves = 0
        errors = []
        import_ref = f"import:{timezone.now().strftime('%Y%m%d%H%M%S')}"

        for r in rows:
            try:
                code = (str(r[key_index['code']]).strip() if key_index.get('code') is not None else '').upper()
                if not code:
                    continue
                name = str(r[key_index['name']]).strip() if key_index.get('name') is not None and r[key_index['name']] is not None else ''
                uom = str(r[key_index['uom']]).strip() if key_index.get('uom') is not None and r[key_index['uom']] is not None else ''
                reorder = to_decimal(r[key_index['reorder_level']], None) if key_index.get('reorder_level') is not None else None
                qty = to_decimal(r[key_index['quantity']], None) if key_index.get('quantity') is not None else None
                batch_no = str(r[key_index['batch_no']]).strip() if key_index.get('batch_no') is not None and r[key_index['batch_no']] is not None else ''
                expiry = parse_date(r[key_index['expiry']]) if key_index.get('expiry') is not None else None
                unit_cost = to_decimal(r[key_index['unit_cost']], None) if key_index.get('unit_cost') is not None else None

                item = InventoryItem.objects.filter(code=code).first()
                if not item:
                    if not name:
                        errors.append(f'Row for code {code} missing name; item not created.')
                        continue
                    item = InventoryItem.objects.create(
                        code=code,
                        name=name,
                        uom=uom or 'unit',
                        reorder_level=(reorder if reorder is not None else Decimal('0')),
                    )
                    created_items += 1
                else:
                    changed = False
                    if name and item.name != name:
                        item.name = name
                        changed = True
                    if uom and item.uom != uom:
                        item.uom = uom
                        changed = True
                    if reorder is not None and item.reorder_level != reorder:
                        item.reorder_level = reorder
                        changed = True
                    if changed:
                        item.save()
                        updated_items += 1

                if mode == 'items_only':
                    continue
                # Stock/batches
                if qty is None:
                    continue
                b, created = Batch.objects.get_or_create(
                    item=item,
                    batch_no=(batch_no or ''),
                    expiry=expiry,
                    defaults={'quantity_on_hand': Decimal('0')}
                )
                if created:
                    created_batches += 1
                old_qoh = b.quantity_on_hand or Decimal('0')
                if replace_qoh:
                    delta = (qty or Decimal('0')) - old_qoh
                    b.quantity_on_hand = (qty or Decimal('0'))
                    b.save(update_fields=['quantity_on_hand'])
                    if delta != 0:
                        StockMovement.objects.create(
                            item=item,
                            batch=b,
                            direction=StockMovement.ADJUST,
                            quantity=abs(delta),
                            reason='import',
                            ref=f'{import_ref}{f"; cost={unit_cost}" if unit_cost is not None else ""}'
                        )
                        created_moves += 1
                        updated_batches += (0 if created else 1)
                else:
                    # add to existing
                    add = (qty or Decimal('0'))
                    if add != 0:
                        b.quantity_on_hand = old_qoh + add
                        b.save(update_fields=['quantity_on_hand'])
                        StockMovement.objects.create(
                            item=item,
                            batch=b,
                            direction=StockMovement.IN,
                            quantity=add,
                            reason='import',
                            ref=f'{import_ref}{f"; cost={unit_cost}" if unit_cost is not None else ""}'
                        )
                        created_moves += 1
                        updated_batches += (0 if created else 1)
            except Exception as e:
                errors.append(str(e)[:180])

        result = {
            'created_items': created_items,
            'updated_items': updated_items,
            'created_batches': created_batches,
            'updated_batches': updated_batches,
            'movements_created': created_moves,
            'errors': errors[:20],
            'error_count': len(errors),
        }
        # HTMX success
        if request.headers.get('HX-Request'):
            # Render partial summary block
            return render(request, 'inventory/import_result.html', {'result': result})

    return render(request, 'inventory/import.html', {'result': result})
