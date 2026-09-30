from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core import signing
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.accounts.models import Facility, StaffProfile, User
from apps.audit.models import AuditEvent
from apps.billing.models import CashSession, Invoice, InvoiceLine, Payment
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.pharmacy.models import Prescription, PrescriptionItem, Backorder
from common.exports import csv_response, xlsx_response
from common.permissions import RolePermission


@pytest.fixture
def clinic(db):
    a = Facility.objects.create(name='Clinic A')
    b = Facility.objects.create(name='Clinic B')
    user = User.objects.create_user('staff', password='test-pass', role='admin')
    StaffProfile.objects.create(user=user, facility=a)
    own = Patient.objects.create(first_name='Own', last_name='Patient', gender='F', facility=a)
    other = Patient.objects.create(first_name='Other', last_name='Patient', gender='M', facility=b)
    api = APIClient()
    api.force_authenticate(user)
    return SimpleNamespace(a=a, b=b, user=user, own=own, other=other, api=api)


@pytest.mark.parametrize('method,action,rules,role,allowed', [
    ('GET', 'list', {'list': ['manager']}, 'nurse', False),
    ('GET', 'list', {'list': ['manager']}, 'manager', True),
    ('GET', 'list', {'list': []}, 'manager', False),
    ('HEAD', 'retrieve', {'GET': ['manager']}, 'nurse', False),
    ('PUT', 'update', {'POST': ['admin']}, 'nurse', False),
    ('GET', 'list', {'POST': ['admin']}, 'nurse', True),
])
def test_role_rules(method, action, rules, role, allowed):
    user = SimpleNamespace(is_authenticated=True, is_active=True, is_superuser=False, role=role)
    request = SimpleNamespace(user=user, method=method)
    view = SimpleNamespace(action=action, role_map=rules)
    assert RolePermission().has_permission(request, view) is allowed


def test_inactive_superuser_is_denied():
    request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, is_active=False, is_superuser=True))
    assert not RolePermission().has_permission(request, SimpleNamespace())


def test_patient_create_assigns_facility_and_rejects_other_facility(clinic):
    payload = {'first_name': 'New', 'last_name': 'Patient', 'gender': 'F'}
    response = clinic.api.post('/api/patients/', payload)
    assert response.status_code == 201
    assert response.data['facility'] == clinic.a.pk
    for facility in (clinic.b.pk, None):
        response = clinic.api.post('/api/patients/', {**payload, 'facility': facility}, format='json')
        assert response.status_code == 400


def test_patient_patch_cannot_move_or_clear_facility(clinic):
    for facility in (clinic.b.pk, None):
        response = clinic.api.patch(f'/api/patients/{clinic.own.pk}/', {'facility': facility}, format='json')
        assert response.status_code == 400
    clinic.own.refresh_from_db()
    assert clinic.own.facility_id == clinic.a.pk


def test_unassigned_staff_cannot_access_or_create_patients(clinic):
    StaffProfile.objects.filter(user=clinic.user).delete()
    user = User.objects.get(pk=clinic.user.pk)
    clinic.api.force_authenticate(user)
    assert clinic.api.get('/api/patients/').data['count'] == 0
    assert clinic.api.get(f'/api/patients/{clinic.own.pk}/').status_code == 404
    response = clinic.api.post('/api/patients/', {'first_name': 'New', 'last_name': 'Patient', 'gender': 'F'})
    assert response.status_code == 400


@pytest.mark.parametrize('endpoint,payload', [
    ('encounters', {}),
    ('orders', {'order_type': 'lab', 'code': 'TEST'}),
    ('prescriptions', {}),
    ('appointments', {'scheduled_for': '2030-10-01T09:00:00+03:00'}),
    ('queue-tickets', {'service': 'triage'}),
])
def test_api_cannot_reference_other_facility_patient(clinic, endpoint, payload):
    payload = {**payload, 'patient': clinic.other.pk}
    if endpoint == 'appointments':
        payload['clinician'] = clinic.user.pk
    response = clinic.api.post(f'/api/{endpoint}/', payload)
    assert response.status_code == 400, response.content
    assert 'patient' in response.data


def test_order_patient_and_encounter_must_match_on_patch(clinic):
    second = Patient.objects.create(first_name='Second', last_name='Patient', gender='M', facility=clinic.a)
    encounter = Encounter.objects.create(patient=clinic.own)
    response = clinic.api.post('/api/orders/', {
        'patient': clinic.own.pk, 'encounter': encounter.pk, 'order_type': 'lab', 'code': 'TEST',
    })
    assert response.status_code == 201
    response = clinic.api.patch(f"/api/orders/{response.data['id']}/", {'patient': second.pk})
    assert response.status_code == 400


@pytest.mark.parametrize('endpoint,payload', [
    ('orders', {'order_type': 'lab', 'code': 'TEST'}),
    ('dispenses', {'item_code': 'TEST'}),
])
@pytest.mark.parametrize('quantity', ['0', '-2', 'NaN'])
def test_invalid_quantities_cannot_create_financial_or_stock_entries(clinic, endpoint, payload, quantity):
    response = clinic.api.post(f'/api/{endpoint}/', {**payload, 'patient': clinic.own.pk, 'quantity': quantity})
    assert response.status_code == 400
    assert 'quantity' in response.data
    assert not InvoiceLine.objects.exists()


def test_reports_scope_rows_and_totals(clinic):
    for patient, amount in ((clinic.own, '25'), (clinic.other, '500')):
        inv = Invoice.objects.create(patient=patient, total_amount=amount)
        InvoiceLine.objects.create(invoice=inv, code=patient.first_name, source_ref=f'test:{inv.pk}', unit_price=Decimal(amount))
        Payment.objects.create(invoice=inv, amount=amount)
    assert Decimal(clinic.api.get('/api/reports/daily-revenue').data['total_revenue']) == 25
    assert clinic.api.get('/api/reports/patient-volumes').data['new_patients'] == 1
    for endpoint in ('raw-invoices', 'raw-payments'):
        response = clinic.api.get('/api/reports/' + endpoint)
        assert response.status_code == 200
        assert {r['patient_id'] for r in response.data['rows']} == {clinic.own.pk}
    assert [r['code'] for r in clinic.api.get('/api/reports/service-mix').data['service_mix']] == ['Own']


@pytest.mark.parametrize('params', [
    {'date': 'invalid'}, {'date': '2026-02-30'}, {'start': '2026-01-01'},
    {'start': '2026-02-02', 'end': '2026-01-01'}, {'date': '2026-01-01', 'end': '2026-01-02'},
])
def test_bad_report_dates_return_400(clinic, params):
    assert clinic.api.get('/api/reports/daily-revenue', params).status_code == 400


@pytest.mark.parametrize('param,value', [('slot', '0'), ('slot', '-1'), ('duration', '0'), ('duration', 'abc'), ('duration', '999999999')])
def test_invalid_slot_parameters_cannot_loop(clinic, client, param, value):
    params = {'clinician': clinic.user.pk, param: value}
    assert clinic.api.get('/api/appointments/available_slots/', params).status_code == 400
    if value != 'abc':  # HTML form intentionally defaults non-numeric values.
        client.force_login(clinic.user)
        assert client.get(reverse('appointments-slots'), params).status_code == 400


def test_pharmacy_ui_rejects_other_facility_objects(clinic, client):
    rx = Prescription.objects.create(patient=clinic.other)
    item = PrescriptionItem.objects.create(prescription=rx, item_code='TEST')
    bo = Backorder.objects.create(patient=clinic.other, item_code='TEST', quantity=1)
    client.force_login(clinic.user)
    urls = [
        (reverse('rx-item-add', args=[rx.pk]), {}),
        (reverse('rx-item-delete', args=[item.pk]), {}),
        (reverse('pharmacy-dispense-create'), {'prescription_item_id': item.pk, 'quantity': 1}),
        (reverse('pharmacy-backorder-fulfill', args=[bo.pk]), {'quantity': 1}),
        (reverse('pharmacy-backorder-close', args=[bo.pk]), {}),
    ]
    for url, payload in urls:
        assert client.post(url, payload).status_code == 404
    assert client.get(reverse('pharmacy-backorder-detail', args=[bo.pk])).status_code == 404


def test_audit_redacts_patient_queries_and_portal_tokens(clinic, client):
    client.force_login(clinic.user)
    client.get('/patients', {'q': 'SensitivePatientSearch'})
    from apps.operations.models import PortalGrant
    from datetime import timedelta
    from django.utils import timezone
    grant = PortalGrant.objects.create(patient=clinic.own, created_by=clinic.user, expires_at=timezone.now()+timedelta(hours=1))
    token = signing.dumps({'p': clinic.own.pk, 'g': str(grant.key)}, salt='patient-portal')
    response = client.get(reverse('portal-view', args=[token]))
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']
    assert response['Referrer-Policy'] == 'no-referrer'
    paths = list(AuditEvent.objects.values_list('path', flat=True))
    assert not any('SensitivePatientSearch' in path or token in path for path in paths)
    assert '/portal/<redacted>/' in paths


@pytest.mark.parametrize('value', ['=1+1', '+cmd', '-cmd', '@SUM(1)', '  =1+1', '\t=1+1'])
def test_exports_do_not_execute_text_formulas(value):
    response = csv_response('test.csv', ['name'], [{'name': value}])
    assert "'" + value in response.content.decode()
    response = xlsx_response('test.xlsx', ['name'], [{'name': value}])
    cell = load_workbook(BytesIO(response.content)).active['A2']
    assert cell.data_type == 's'
    assert cell.value == "'" + value


@pytest.mark.parametrize('name', ['inventory-po-approve', 'inventory-po-close', 'inventory-po-cancel', 'inventory-grn-post'])
def test_procurement_mutations_reject_get(clinic, client, name):
    client.force_login(clinic.user)
    assert client.get(reverse(name, args=[999])).status_code == 405


def test_logout_uses_post(clinic, client):
    client.force_login(clinic.user)
    assert client.get(reverse('logout')).status_code == 405
    assert client.post(reverse('logout')).status_code == 302


@pytest.mark.parametrize('name', [
    'home', 'patients-list', 'appointments-calendar', 'ehr-board', 'pharmacy-board',
    'inventory-stock', 'inventory-po-list', 'inventory-grn-list', 'cashier', 'cashbook',
])
def test_core_screens_render_after_framework_upgrade(clinic, client, name):
    client.force_login(clinic.user)
    assert client.get(reverse(name)).status_code == 200


def test_procurement_requires_csrf_and_valid_post_succeeds(clinic):
    from django.test import Client
    from apps.inventory.models import PurchaseOrder, Supplier, PurchaseOrderLine, InventoryItem

    supplier = Supplier.objects.create(name='Supplier')
    requester=User.objects.create_user(username='procurement-requester',role='store')
    po = PurchaseOrder.objects.create(supplier=supplier, facility=clinic.a,created_by=requester)
    PurchaseOrderLine.objects.create(po=po,item=InventoryItem.objects.create(code='CSRF-PO',name='Synthetic item'),quantity_ordered=1,unit_cost=10)
    client = Client(enforce_csrf_checks=True)
    client.force_login(clinic.user)
    url = reverse('inventory-po-approve', args=[po.pk])
    assert client.post(url).status_code == 403
    page = client.get(reverse('inventory-po-list'))
    assert page.status_code == 200
    response = client.post(url, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    assert response.status_code == 302
    po.refresh_from_db()
    assert po.status == PurchaseOrder.APPROVED
