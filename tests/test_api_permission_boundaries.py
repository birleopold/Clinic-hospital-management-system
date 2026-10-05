"""API/UI read parity and financial admin workflow bypass regressions."""
from datetime import timedelta, time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Facility, FacilityConfiguration, StaffProfile, User
from apps.appointments.models import DoctorTimeOff, DoctorWeeklyAvailability
from apps.billing.models import CashSession, Invoice, InvoiceLine, Payment
from apps.demographics.models import Patient
from apps.inventory.models import InventoryItem, PurchaseOrder, PurchaseOrderLine, Supplier
from apps.orders.models import Order, OrderResult
from apps.orders.permissions import filter_visible_results
from apps.orders.serializers import OrderSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def boundary():
    facility = Facility.objects.create(name='Boundary clinic')
    outside = Facility.objects.create(name='Other clinic')
    user = User.objects.create_user('boundary-staff', role='admin')
    StaffProfile.objects.update_or_create(user=user, defaults={'facility': facility})
    patient = Patient.objects.create(
        first_name='Boundary', last_name='Patient', gender='F', facility=facility,
        insurance_id='Private insurance sentinel', guardian_phone='Private guardian sentinel',
        email='private@example.test', address='Private address sentinel',
    )
    other_patient = Patient.objects.create(first_name='Other', last_name='Patient', gender='M', facility=outside)
    order = Order.objects.create(patient=patient, order_type='lab', code='BOUNDARY', billable=False)
    draft = OrderResult.objects.create(order=order, result_text='Unreleased sentinel')
    released = OrderResult.objects.create(order=order, result_text='Released sentinel', approved_at=timezone.now())
    other_order = Order.objects.create(patient=other_patient, order_type='lab', code='OTHER', billable=False)
    other_result = OrderResult.objects.create(order=other_order, result_text='Outside sentinel', approved_at=timezone.now())
    api = APIClient()
    api.force_authenticate(user)
    return SimpleNamespace(facility=facility, outside=outside, user=user, patient=patient,
                           other_patient=other_patient, order=order, draft=draft,
                           released=released, other_result=other_result, api=api)


def set_role(boundary, role):
    boundary.user.role = role
    boundary.user.save(update_fields=['role'])
    boundary.api.force_authenticate(boundary.user)


@pytest.mark.parametrize('role', ['store', 'radiology', 'unknown'])
@pytest.mark.parametrize('method', ['get', 'head'])
def test_patient_directory_denies_non_chart_roles(boundary, role, method):
    set_role(boundary, role)
    for url in ('/api/patients/', f'/api/patients/{boundary.patient.pk}/'):
        assert getattr(boundary.api, method)(url).status_code == 403


@pytest.mark.parametrize('role', ['nurse', 'pharmacy', 'lab', 'cashier', 'manager'])
def test_patient_worklist_roles_get_only_scoped_identity(boundary, role):
    set_role(boundary, role)
    response = boundary.api.get('/api/patients/')
    assert response.status_code == 200
    assert response.data['count'] == 1
    data = response.data['results'][0]
    assert data['id'] == boundary.patient.pk
    assert set(data) == {'id', 'medical_record_id', 'first_name', 'last_name', 'other_names',
                         'gender', 'date_of_birth', 'phone', 'facility'}
    response = boundary.api.get(f'/api/patients/{boundary.patient.pk}/')
    assert set(response.data) == set(data)
    assert boundary.api.get(f'/api/patients/{boundary.other_patient.pk}/').status_code == 404
    assert boundary.api.patch(f'/api/patients/{boundary.patient.pk}/', {'phone': '123'}).status_code == 403


@pytest.mark.parametrize('role', ['admin', 'reception', 'clinician'])
def test_registration_and_clinical_roles_keep_full_patient_reads(boundary, role):
    set_role(boundary, role)
    response = boundary.api.get(f'/api/patients/{boundary.patient.pk}/')
    assert response.status_code == 200
    assert response.data['insurance_id'] == 'Private insurance sentinel'


def test_nurse_results_are_released_only_in_lists_details_and_nested_orders(boundary):
    set_role(boundary, 'nurse')
    response = boundary.api.get('/api/order-results/')
    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [boundary.released.pk]
    for method in ('get', 'head'):
        assert getattr(boundary.api, method)(f'/api/order-results/{boundary.draft.pk}/').status_code == 404
        assert getattr(boundary.api, method)(f'/api/order-results/{boundary.released.pk}/').status_code == 200
    assert boundary.api.get(f'/api/order-results/{boundary.other_result.pk}/').status_code == 404
    for url in ('/api/orders/', f'/api/orders/{boundary.order.pk}/'):
        response = boundary.api.get(url)
        row = response.data['results'][0] if url == '/api/orders/' else response.data
        assert [result['id'] for result in row['results']] == [boundary.released.pk]
        assert b'Unreleased sentinel' not in response.content
    # An unprefetched serializer must apply the same policy, including no-request use.
    data = OrderSerializer(boundary.order, context={'request': SimpleNamespace(user=boundary.user)}).data
    assert [row['id'] for row in data['results']] == [boundary.released.pk]
    assert OrderSerializer(boundary.order).data['results'] == []


@pytest.mark.parametrize('role', ['admin', 'clinician', 'lab'])
def test_result_reviewers_keep_draft_review_with_facility_scope(boundary, role):
    set_role(boundary, role)
    response = boundary.api.get('/api/order-results/')
    assert {row['id'] for row in response.data['results']} == {boundary.draft.pk, boundary.released.pk}
    assert boundary.api.get(f'/api/order-results/{boundary.draft.pk}/').status_code == 200
    response = boundary.api.get(f'/api/orders/{boundary.order.pk}/')
    assert {row['id'] for row in response.data['results']} == {boundary.draft.pk, boundary.released.pk}


@pytest.mark.parametrize('role', ['reception', 'cashier', 'manager', 'pharmacy', 'store', 'radiology'])
def test_result_helper_and_api_deny_non_result_roles(boundary, role):
    set_role(boundary, role)
    assert not filter_visible_results(OrderResult.objects.all(), boundary.user).exists()
    assert boundary.api.get('/api/order-results/').status_code == 403


def test_result_helper_is_fail_closed_and_preserves_service_scope(boundary):
    assert not filter_visible_results(OrderResult.objects.all(), AnonymousUser()).exists()
    boundary.user.is_active = False
    assert not filter_visible_results(OrderResult.objects.all(), boundary.user).exists()
    boundary.user.is_active = True
    FacilityConfiguration.objects.create(
        facility=boundary.facility, service_type='custom', display_name='Clinic',
        enabled_services=['patients', 'clinical'], configured_by=boundary.user,
    )
    if hasattr(boundary.user, '_service_profile'):
        del boundary.user._service_profile
    procedure = Order.objects.create(patient=boundary.patient, order_type='procedure', code='PROC', billable=False)
    result = OrderResult.objects.create(order=procedure, result_text='Procedure result')
    response = boundary.api.get('/api/order-results/')
    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [result.pk]
    assert boundary.api.get(f'/api/order-results/{boundary.released.pk}/').status_code == 404
    assert boundary.api.get(f'/api/orders/{boundary.order.pk}/').status_code == 404


@pytest.mark.parametrize('role', ['nurse', 'lab', 'pharmacy', 'cashier', 'manager', 'store', 'radiology'])
def test_appointment_api_matches_calendar_read_roles(boundary, role):
    set_role(boundary, role)
    assert boundary.api.get('/api/appointments/').status_code == 403
    assert boundary.api.head('/api/appointments/').status_code == 403


@pytest.mark.parametrize('role', ['admin', 'reception', 'clinician'])
def test_staff_availability_reads_cannot_cross_facilities(boundary, client, role):
    set_role(boundary, role)
    own = User.objects.create_user('own-doctor', role='clinician')
    other = User.objects.create_user('other-doctor', role='clinician')
    StaffProfile.objects.update_or_create(user=own, defaults={'facility': boundary.facility})
    StaffProfile.objects.update_or_create(user=other, defaults={'facility': boundary.outside})
    now = timezone.now()
    for doctor in (own, other):
        DoctorWeeklyAvailability.objects.create(clinician=doctor, day_of_week=now.weekday(), start_time=time(9), end_time=time(17))
        DoctorTimeOff.objects.create(clinician=doctor, start=now, end=now+timedelta(hours=1), reason='Private reason')
    for basename, model in (('doctor-availability', DoctorWeeklyAvailability), ('doctor-timeoff', DoctorTimeOff)):
        response = boundary.api.get(reverse(f'{basename}-list'))
        assert response.status_code == 200
        assert {row['clinician'] for row in response.data['results']} == {own.pk}
        foreign = model.objects.get(clinician=other)
        assert boundary.api.get(reverse(f'{basename}-detail', args=[foreign.pk])).status_code == 404
    assert boundary.api.get('/api/appointments/available_slots/', {'clinician': other.pk}).status_code == 404
    assert boundary.api.get('/api/appointments/available_slots/', {'clinician': own.pk}).status_code == 200
    client.force_login(boundary.user)
    response = client.get('/appointments/schedule')
    assert response.status_code == 200
    assert {doctor.pk for doctor in response.context['clinicians']} == {own.pk} | ({boundary.user.pk} if role == 'clinician' else set())
    assert client.get('/appointments/schedule', {'clinician': other.pk}).status_code == 404
    assert client.get('/appointments/slots', {'clinician': other.pk}).status_code == 404



@pytest.mark.parametrize('role', ['reception', 'clinician', 'nurse', 'lab', 'cashier', 'radiology'])
@pytest.mark.parametrize('url', ['/api/inventory/batches/', '/api/inventory/movements/'])
def test_stock_ledger_api_matches_stock_workspace_roles(boundary, role, url):
    set_role(boundary, role)
    assert boundary.api.get(url).status_code == 403


@pytest.mark.parametrize('role', ['admin', 'pharmacy', 'store', 'manager'])
def test_stock_workspace_roles_keep_ledger_reads(boundary, role):
    set_role(boundary, role)
    assert boundary.api.get('/api/inventory/batches/').status_code == 200
    assert boundary.api.get('/api/inventory/movements/').status_code == 200


def financial_records(boundary):
    supplier = Supplier.objects.create(name='Boundary supplier')
    item = InventoryItem.objects.create(code='BOUNDARY-ITEM', name='Boundary item')
    po = PurchaseOrder.objects.create(facility=boundary.facility, supplier=supplier, created_by=boundary.user)
    po_line = PurchaseOrderLine.objects.create(po=po, item=item, quantity_ordered=2, unit_cost=25)
    invoice = Invoice.objects.create(patient=boundary.patient, total_amount=50)
    line = InvoiceLine.objects.create(invoice=invoice, code='MANUAL', quantity=2, unit_price=25, source_ref='test-boundary')
    session = CashSession.objects.create(opened_by=boundary.user, opening_float=10, expected_cash=10)
    return po, po_line, invoice, line, session


def test_financial_admin_rejects_mutations_even_for_superusers(boundary, client):
    po, po_line, invoice, line, session = financial_records(boundary)
    superuser = User.objects.create_superuser('boundary-owner', 'owner@example.test', 'test')
    client.force_login(superuser)
    request = RequestFactory().get('/admin/')
    request.user = superuser
    for obj in (po, invoice, session):
        model_admin = admin.site._registry[type(obj)]
        prefix = f'admin:{obj._meta.app_label}_{obj._meta.model_name}'
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request, obj)
        assert not model_admin.has_delete_permission(request, obj)
        assert not model_admin.get_actions(request)
        response = client.get(reverse(prefix+'_change', args=[obj.pk]))
        assert response.status_code == 200
        assert b'Open ' in response.content
        assert client.post(reverse(prefix+'_add'), {}).status_code == 403
        assert client.post(reverse(prefix+'_change', args=[obj.pk]), {
            'status': 'approved', 'total_amount': '1', 'paid_amount': '50',
            'expected_cash': '500', 'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '1',
            'lines-0-id': po_line.pk if obj == po else line.pk, 'lines-0-quantity_ordered': '100',
            'lines-0-unit_cost': '0', 'lines-0-unit_price': '0',
        }).status_code == 403
        assert client.post(reverse(prefix+'_delete', args=[obj.pk]), {'post': 'yes'}).status_code == 403
        for inline in model_admin.get_inline_instances(request, obj):
            assert not inline.has_add_permission(request, obj)
            assert not inline.has_change_permission(request, obj)
            assert not inline.has_delete_permission(request, obj)
            assert set(field.name for field in inline.model._meta.fields) <= set(inline.get_readonly_fields(request, obj))
    po.refresh_from_db(); po_line.refresh_from_db(); invoice.refresh_from_db(); line.refresh_from_db(); session.refresh_from_db()
    assert po.status == PurchaseOrder.DRAFT and po.approved_by_id is None
    assert po_line.quantity_ordered == 2 and po_line.unit_cost == 25
    assert invoice.total_amount == Decimal('50') and invoice.paid_amount == 0
    assert line.unit_price == 25 and line.line_total == 50
    assert session.expected_cash == 10


def test_financial_admin_inspection_is_facility_scoped(boundary):
    po, _, invoice, _, _ = financial_records(boundary)
    other_po = PurchaseOrder.objects.create(facility=boundary.outside, supplier=po.supplier)
    other_invoice = Invoice.objects.create(patient=boundary.other_patient)
    request = RequestFactory().get('/admin/')
    request.user = boundary.user
    assert list(admin.site._registry[PurchaseOrder].get_queryset(request)) == [po]
    assert list(admin.site._registry[Invoice].get_queryset(request)) == [invoice]
    assert other_po.pk != po.pk and other_invoice.pk != invoice.pk


@pytest.mark.parametrize('services,visible', [
    (['patients', 'appointments', 'clinical'], {'triage', 'consult'}),
    (['patients', 'appointments', 'lab'], {'lab'}),
    (['patients', 'appointments', 'pharmacy', 'inventory', 'billing'], {'pharmacy', 'cashier'}),
])
def test_queue_services_are_filtered_in_ui_api_and_forms(boundary, client, services, visible):
    from apps.appointments.models import QueueTicket
    from apps.appointments.serializers import QueueTicketSerializer
    FacilityConfiguration.objects.create(
        facility=boundary.facility, service_type='custom', display_name='Clinic',
        enabled_services=services, configured_by=boundary.user,
    )
    if hasattr(boundary.user, '_service_profile'):
        del boundary.user._service_profile
    tickets = {service: QueueTicket.objects.create(patient=boundary.patient, service=service)
               for service, _ in QueueTicket.SERVICE_CHOICES}
    client.force_login(boundary.user)
    response = client.get('/queues')
    assert response.status_code == 200
    assert {code for code, _ in response.context['services']} == visible
    assert set(response.context['data']) == visible
    response = boundary.api.get('/api/queue-tickets/')
    assert {row['service'] for row in response.data['results']} == visible
    response = boundary.api.get('/api/queue-tickets/summary/')
    assert {row['service'] for row in response.data} == visible
    form = QueueTicketSerializer(context={'request': SimpleNamespace(user=boundary.user)})
    assert set(form.fields['service'].choices) == visible
    for service, ticket in tickets.items():
        expected = 200 if service in visible else 404
        assert client.get(f'/queues/{service}').status_code == expected
        assert boundary.api.get(f'/api/queue-tickets/{ticket.pk}/').status_code == expected
        response = boundary.api.post('/api/queue-tickets/enqueue/', {
            'patient': boundary.patient.pk, 'service': service,
        })
        assert response.status_code == (201 if service in visible else 400)
        if service not in visible:
            assert boundary.api.post(f'/api/queue-tickets/{ticket.pk}/start/').status_code == 404
    allowed_ticket = tickets[next(iter(visible))]
    disabled = next(service for service in tickets if service not in visible)
    assert boundary.api.patch(f'/api/queue-tickets/{allowed_ticket.pk}/', {'service': disabled}).status_code == 400


def test_queues_require_appointments_even_when_downstream_service_enabled(boundary, client):
    from apps.appointments.serializers import QueueTicketSerializer
    FacilityConfiguration.objects.create(
        facility=boundary.facility, service_type='custom', display_name='Clinic',
        enabled_services=['patients', 'lab'], configured_by=boundary.user,
    )
    client.force_login(boundary.user)
    for url in ('/queues', '/queues/lab', '/api/queue-tickets/'):
        assert client.get(url).status_code == 404
    serializer = QueueTicketSerializer(
        data={'patient': boundary.patient.pk, 'service': 'lab'},
        context={'request': SimpleNamespace(user=boundary.user)},
    )
    assert not serializer.is_valid()
