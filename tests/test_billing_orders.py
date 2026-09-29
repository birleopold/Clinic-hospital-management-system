from decimal import Decimal

import pytest

from apps.billing.models import InvoiceLine
from apps.demographics.models import Patient
from apps.orders.models import Order


@pytest.mark.django_db
def test_billable_order_creates_invoice_line():
    patient = Patient.objects.create(first_name='Ann', last_name='Test', gender=Patient.F)
    order = Order.objects.create(
        patient=patient,
        order_type=Order.LAB,
        code='TST',
        description='Test service',
        quantity=Decimal('1'),
        billable=True,
    )
    line = InvoiceLine.objects.filter(source_ref=f'order:{order.id}').first()
    assert line is not None
    assert line.quantity == Decimal('1')


@pytest.mark.django_db
def test_cancel_order_adds_reversal_line_nets_zero():
    patient = Patient.objects.create(first_name='Bob', last_name='Test', gender=Patient.M)
    order = Order.objects.create(
        patient=patient,
        order_type=Order.LAB,
        code='TST2',
        billable=True,
        quantity=Decimal('2'),
    )
    assert InvoiceLine.objects.filter(source_ref=f'order:{order.id}').exists()

    order.status = Order.CANCELLED
    order.save(update_fields=['status'])

    assert InvoiceLine.objects.filter(source_ref=f'order:{order.id}:reversal').exists()
    orig = InvoiceLine.objects.get(source_ref=f'order:{order.id}')
    rev = InvoiceLine.objects.get(source_ref=f'order:{order.id}:reversal')
    assert orig.line_total + rev.line_total == Decimal('0')
