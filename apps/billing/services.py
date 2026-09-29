from decimal import Decimal
from typing import Optional

from django.db import transaction

from .models import PriceList, PriceListItem, Invoice, InvoiceLine, Payment


def get_active_pricelist() -> Optional[PriceList]:
    qs = PriceList.objects.filter(is_active=True).order_by('-effective_date', '-id')
    return qs.first()


def price_for(code: str) -> Optional[Decimal]:
    pl = get_active_pricelist()
    if not pl:
        return None
    item = PriceListItem.objects.filter(pricelist=pl, code=code, active=True).first()
    return item.amount if item else None


def get_or_create_open_invoice(patient) -> Invoice:
    inv = Invoice.objects.filter(patient=patient, status=Invoice.DRAFT).order_by('-id').first()
    if inv:
        return inv
    return Invoice.objects.create(patient=patient)


def recalc_invoice(invoice: Invoice) -> None:
    total = sum((line.line_total for line in invoice.lines.all()), Decimal('0.00'))
    invoice.total_amount = total
    invoice.save(update_fields=['total_amount'])


def add_line_from_order(order) -> InvoiceLine:
    source_ref = f"order:{order.id}"
    invoice = get_or_create_open_invoice(order.patient)
    unit_price = price_for(order.code) or Decimal('0.00')
    with transaction.atomic():
        line, _ = InvoiceLine.objects.get_or_create(
            source_ref=source_ref,
            defaults={
                'invoice': invoice,
                'code': order.code,
                'description': order.description or order.code,
                'quantity': order.quantity,
                'unit_price': unit_price,
            }
        )
        recalc_invoice(invoice)
        return line


def ready_open_invoices_for_patient(patient) -> None:
    qs = Invoice.objects.filter(patient=patient, status=Invoice.DRAFT)
    for inv in qs:
        recalc_invoice(inv)
        if inv.total_amount > 0:
            inv.status = Invoice.READY
            inv.save(update_fields=['status'])


def add_line_from_dispense(dispense) -> InvoiceLine:
    source_ref = f"dispense:{dispense.id}"
    invoice = get_or_create_open_invoice(dispense.patient)
    unit_price = price_for(dispense.item_code) or Decimal('0.00')
    with transaction.atomic():
        line, _ = InvoiceLine.objects.get_or_create(
            source_ref=source_ref,
            defaults={
                'invoice': invoice,
                'code': dispense.item_code,
                'description': dispense.item_name or dispense.item_code,
                'quantity': dispense.quantity,
                'unit_price': unit_price,
            }
        )
        recalc_invoice(invoice)
        return line


def reverse_line_from_order(order) -> Optional[InvoiceLine]:
    """
    Idempotent credit for a billable order line: original source_ref is order:{id};
    reversal uses order:{id}:reversal. Original line is left in place for audit.
    """
    orig_ref = f"order:{order.id}"
    rev_ref = f"order:{order.id}:reversal"
    with transaction.atomic():
        orig = (
            InvoiceLine.objects.select_related('invoice')
            .select_for_update(of=('self',))
            .filter(source_ref=orig_ref)
            .first()
        )
        if not orig:
            return None
        inv = Invoice.objects.select_for_update().get(pk=orig.invoice_id)
        desc = f"Reversal (order #{order.id} cancelled): {orig.description or orig.code}"[:255]
        rev, created = InvoiceLine.objects.get_or_create(
            source_ref=rev_ref,
            defaults={
                'invoice': inv,
                'code': orig.code,
                'description': desc,
                'quantity': -orig.quantity,
                'unit_price': orig.unit_price,
            },
        )
        if created:
            recalc_invoice(inv)
            if inv.status == Invoice.READY and inv.total_amount <= 0:
                inv.status = Invoice.DRAFT
                inv.save(update_fields=['status'])
        return rev
