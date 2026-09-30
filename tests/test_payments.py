import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Facility, StaffProfile, User
from apps.billing.models import CashSession, Invoice, Payment
from apps.demographics.models import Patient


@pytest.fixture
def cashdesk(db):
    facility = Facility.objects.create(name='Clinic')
    user = User.objects.create_user('cashier', role='cashier')
    StaffProfile.objects.create(user=user, facility=facility)
    patient = Patient.objects.create(first_name='Test', last_name='Patient', gender='F', facility=facility)
    invoice = Invoice.objects.create(patient=patient, total_amount=100, status=Invoice.READY)
    api = APIClient()
    api.force_authenticate(user)
    return api, user, invoice


@pytest.mark.parametrize('amount', ['-1', '0', 'NaN', 'Infinity', 'invalid', '0.001', '101', '999999999999999999'])
def test_invalid_payments_leave_no_side_effects(cashdesk, amount):
    api, user, invoice = cashdesk
    response = api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': amount})
    assert response.status_code == 400
    assert not Payment.objects.exists()
    assert not CashSession.objects.exists()
    invoice.refresh_from_db()
    assert invoice.paid_amount == 0


def test_payments_update_totals_and_own_session(cashdesk):
    api, user, invoice = cashdesk
    other_user = User.objects.create_user('other')
    other_session = CashSession.objects.create(opened_by=other_user)
    for amount in ('40', '60'):
        response = api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': amount, 'cash_session': other_session.pk})
        assert response.status_code == 201
        assert Payment.objects.get(pk=response.data['id']).cash_session.opened_by_id == user.pk
    invoice.refresh_from_db()
    assert invoice.paid_amount == Decimal('100')
    assert invoice.status == Invoice.PAID
    assert CashSession.objects.get(opened_by=user).expected_cash == Decimal('100')
    assert api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': '1'}).status_code == 400


def test_payment_ledger_cannot_be_rewritten(cashdesk):
    api, user, invoice = cashdesk
    response = api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': '10'})
    url = f"/api/payments/{response.data['id']}/"
    for method in ('put', 'patch', 'delete'):
        assert getattr(api, method)(url, {'amount': '90'}).status_code in (403, 405)
    assert Payment.objects.get().amount == Decimal('10')


def test_cross_facility_and_cancelled_invoice_cannot_be_paid(cashdesk):
    api, user, invoice = cashdesk
    invoice.status = Invoice.CANCELLED
    invoice.save()
    assert api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': '10'}).status_code == 400
    invoice.status = Invoice.READY
    invoice.save()
    invoice.patient.facility = Facility.objects.create(name='Other')
    invoice.patient.save()
    assert api.post('/api/payments/', {'idempotency_key':str(uuid.uuid4()),'invoice': invoice.pk, 'amount': '10'}).status_code == 400
    assert not Payment.objects.exists()
