import io
import uuid
from datetime import timedelta
from decimal import Decimal
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
import pytest
from apps.accounts.models import User, FacilityConfiguration
from apps.appointments.models import Appointment
from apps.demographics.models import Patient
from apps.operations.models import OperatingBudget, OperatingExpense, ExpenseSettlement, PortalGrant, PortalRecipient, AppointmentRequest, ManagementCase, Attendance, ShiftCover
from apps.operations import settlement_services as settlements, workforce_services as workforce
from tests.test_workforce import team, shift

pytestmark=pytest.mark.django_db


def expense(t):
    budget=OperatingBudget.objects.create(facility=t.f,cost_centre='Synthetic test',starts_on=timezone.localdate(),ends_on=timezone.localdate()+timedelta(days=30),amount=1000,status='approved',created_by=t.manager,reviewed_by=t.manager2)
    return OperatingExpense.objects.create(budget=budget,incurred_on=timezone.localdate(),payee='Synthetic supplier',reference='EXP-TEST',description='Reviewed test invoice',amount=800,status='approved',created_by=t.manager,reviewed_by=t.manager2)


def payment_data(amount=300):
    return dict(amount=Decimal(amount),paid_on=timezone.localdate(),method='bank',account_reference='Synthetic bank account',transaction_reference=str(uuid.uuid4()),evidence='Synthetic statement reference',request_key=uuid.uuid4())


def patient_link(t, scopes):
    patient=Patient.objects.create(facility=t.f,first_name='Scoped',last_name='Patient',gender='F')
    grant=PortalGrant.objects.create(patient=patient,created_by=t.reception,expires_at=timezone.now()+timedelta(hours=1))
    PortalRecipient.objects.create(grant=grant,created_by=t.reception,recipient_name='Verified recipient',relationship='patient',verification_reference='In-person test verification',allow_appointment_requests='appointments' in scopes,scopes=scopes)
    token=signing.dumps({'p':patient.pk,'g':str(grant.key)},salt='patient-portal')
    return patient,grant,token


def test_structure_configuration_uses_existing_records_and_facility_scope(client,team):
    from apps.accounts.models import Department
    from apps.operations.models import ServiceRoom
    client.force_login(team.manager)
    data={'facility':team.f.pk,'name':'Patient reception','directions':'Ground floor, reception desk'}
    assert client.post('/accounts/structure/rooms/',data).status_code==302
    room=ServiceRoom.objects.get(facility=team.f,name='Patient reception')
    assert client.post('/accounts/structure/rooms/',{**data,'name':'PATIENT RECEPTION'}).status_code==200
    assert ServiceRoom.objects.filter(facility=team.f).count()==1
    assert client.post(f'/accounts/structure/rooms/{room.pk}/',{**data,'directions':'Revised signed directions'}).status_code==302
    room.refresh_from_db();assert room.directions=='Revised signed directions'
    assert client.post('/accounts/structure/departments/',{'facility':team.f.pk,'name':'New department','code':'NEW','is_active':'on'}).status_code==302
    assert Department.objects.filter(facility=team.f,code='NEW').count()==1
    client.force_login(team.outsider)
    assert client.get(f'/accounts/structure/rooms/{room.pk}/').status_code==404
    assert client.post('/accounts/structure/rooms/',data).status_code==200
    assert ServiceRoom.objects.filter(facility=team.f).count()==1
    client.force_login(team.reception)
    assert client.get('/accounts/structure/rooms/').status_code==403


def test_settlement_replay_limits_independence_and_report(client,team):
    t=team;obj=expense(t);data=payment_data()
    one=settlements.record_settlement(t.manager,obj.pk,**data)
    assert settlements.record_settlement(t.manager,obj.pk,**data).pk==one.pk
    with pytest.raises(ValidationError,match='reference conflict'):settlements.record_settlement(t.manager,obj.pk,**{**data,'amount':Decimal(301)})
    with pytest.raises(ValidationError,match='different supervisor'):settlements.reconcile(t.manager,one.pk,'confirmed','Self')
    with pytest.raises(PermissionDenied):settlements.reconcile(t.outsider,one.pk,'confirmed','Other site')
    with pytest.raises(ValidationError,match='outstanding'):settlements.record_settlement(t.manager,obj.pk,**payment_data(501))
    settlements.reconcile(t.manager2,one.pk,'confirmed','Statement checked')
    assert settlements.reconcile(t.manager2,one.pk,'confirmed','Retry').pk==one.pk
    with pytest.raises(ValidationError,match='immutable'):settlements.reconcile(t.manager2,one.pk,'rejected','Changed')
    client.force_login(t.manager)
    assert client.get(f'/suite/management/expenses/{obj.pk}/').status_code==200
    response=client.get('/suite/management/expenses/report/')
    assert response.status_code==200 and response.context['settled']==300
    assert b'not profit' in response.content
    assert client.get('/suite/management/expenses/report/?start=2026-10-10&end=2026-01-01').context['form'].errors
    assert client.get('/suite/management/expenses/').content.count(b'Settlement evidence and reconciliation')==1
    client.force_login(t.outsider)
    assert client.get(f'/suite/management/expenses/{obj.pk}/').status_code==404


def test_rejected_settlement_does_not_count_or_reserve(team):
    obj=expense(team);a=settlements.record_settlement(team.manager,obj.pk,**payment_data(800))
    settlements.reconcile(team.manager2,a.pk,'rejected','Not in statement')
    b=settlements.record_settlement(team.manager,obj.pk,**payment_data(800))
    assert b.status=='pending'
    with pytest.raises(ValidationError,match='already recorded'):settlements.record_settlement(team.manager,obj.pk,**{**payment_data(),'transaction_reference':a.transaction_reference})


def test_settlement_form_retry_returns_existing_record(client,team):
    obj=expense(team);client.force_login(team.manager)
    data=payment_data();url=f'/suite/management/expenses/{obj.pk}/'
    assert client.post(url,data).status_code==302
    assert client.post(url,data).status_code==302
    assert ExpenseSettlement.objects.filter(expense=obj).count()==1
    response=client.post(url,{**data,'amount':301})
    assert response.status_code==200 and b'reference conflict' in response.content


def test_cash_flow_sources_reconcile_and_keep_date_scope_on_pagination(client,team):
    from apps.billing.models import Invoice,Payment
    from apps.operations.models import Refund
    patient=Patient.objects.create(facility=team.f,first_name='Synthetic',last_name='Cash flow',gender='F')
    invoice=Invoice.objects.create(patient=patient,total_amount=1000)
    payments=[Payment.objects.create(invoice=invoice,amount=10) for _ in range(26)]
    Refund.objects.create(payment=payments[0],amount=5,reason='Reviewed test refund',status='approved',approved_at=timezone.now(),approved_by=team.manager2,created_by=team.manager)
    outsider=Patient.objects.create(facility=team.other,first_name='Other',last_name='Facility',gender='F')
    other_invoice=Invoice.objects.create(patient=outsider,total_amount=1000)
    Payment.objects.create(invoice=other_invoice,amount=999)
    client.force_login(team.manager)
    day=timezone.localdate().isoformat()
    data={'start':day,'end':day,'source':'collections'}
    response=client.get('/suite/management/expenses/report/',data)
    assert response.context['collected']==260 and response.context['refunds']==5 and response.context['net']==255
    assert response.context['page'].paginator.count==26
    assert f'start={day}&amp;end={day}&amp;source=collections&amp;page=2'.encode() in response.content
    second=client.get('/suite/management/expenses/report/',{**data,'page':2})
    assert len(second.context['page'])==1 and second.context['collected']==260
    returned=client.get('/suite/management/expenses/report/',{**data,'source':'refunds'})
    assert b'Disbursed refund #' in returned.content and returned.context['page'].paginator.count==1


def test_portal_scopes_block_data_actions_and_downloads(client,team):
    patient,grant,token=patient_link(team,['appointments'])
    url='/portal/'+token
    response=client.get(url)
    assert response.status_code==200
    assert b'Request an appointment' in response.content
    assert b'Diagnostic Results' not in response.content and b'Invoices' not in response.content
    assert client.get(url+'/results/999').status_code==403
    assert client.get(url+'/feedback/').status_code==403
    assert client.post(url+'/revoke/').status_code==200
    assert client.get(url).status_code==403


def test_patient_reschedule_preserves_original_and_retries(client,team):
    t=team;patient,grant,token=patient_link(t,['appointments'])
    appointment=Appointment.objects.create(patient=patient,clinician=t.doctor,scheduled_for=t.now+timedelta(days=2))
    url=f'/portal/{token}/appointments/{appointment.pk}/change/'
    data={'kind':'reschedule','preferred_date':timezone.localdate()+timedelta(days=3),'reason':'Patient availability','request_key':uuid.uuid4()}
    assert client.post(url,data).status_code==302
    assert client.post(url,data).status_code==302
    assert AppointmentRequest.objects.count()==1
    assert Appointment.objects.count()==1
    appointment.refresh_from_db();original=appointment.scheduled_for
    obj=AppointmentRequest.objects.get()
    client.force_login(t.reception)
    review={'decision':'booked','scheduled_for':t.now+timedelta(days=3),'duration_minutes':30,'response_note':'Reschedule agreed'}
    assert client.post(f'/suite/appointment-requests/{obj.pk}/',review).status_code==302
    assert client.post(f'/suite/appointment-requests/{obj.pk}/',review).status_code==302
    appointment.refresh_from_db();assert appointment.scheduled_for!=original and Appointment.objects.count()==1
    client.logout();assert b'Upcoming bookings' in client.get('/portal/'+token).content


def test_patient_cancellation_review_and_stale_booking(client,team):
    t=team;patient,grant,token=patient_link(t,['appointments'])
    appointment=Appointment.objects.create(patient=patient,clinician=t.doctor,scheduled_for=t.now+timedelta(days=2))
    data={'kind':'cancel','reason':'Cannot attend','request_key':uuid.uuid4()}
    assert client.post(f'/portal/{token}/appointments/{appointment.pk}/change/',data).status_code==302
    appointment.refresh_from_db();assert appointment.status=='scheduled'
    obj=AppointmentRequest.objects.get();client.force_login(t.reception)
    assert client.post(f'/suite/appointment-requests/{obj.pk}/',{'decision':'booked','response_note':'Cancellation confirmed'}).status_code==302
    appointment.refresh_from_db();assert appointment.status=='cancelled' and Appointment.objects.count()==1


def test_portal_feedback_uses_existing_register_and_hides_internal_notes(client,team):
    patient,grant,token=patient_link(team,['feedback'])
    url='/portal/'+token
    data={'title':'Synthetic waiting-room feedback','details':'Test feedback only','request_key':uuid.uuid4()}
    for _ in range(2):assert client.post(url+'/feedback/',data).status_code==302
    assert ManagementCase.objects.count()==1
    case=ManagementCase.objects.get();case.resolution='Restricted internal investigation';case.save()
    response=client.get(url)
    assert b'Synthetic waiting-room feedback' in response.content
    assert b'Restricted internal investigation' not in response.content
    client.force_login(team.manager)
    assert b'Test feedback only' in client.get('/suite/management/cases/').content
    client.force_login(team.outsider)
    assert b'Test feedback only' not in client.get('/suite/management/cases/').content


def test_atomic_swap_both_accept_and_conflict_rollback(client,team):
    t=team
    a=shift(t,start=t.now+timedelta(days=2),end=t.now+timedelta(days=2,hours=4))
    b=shift(t,staff=t.cover,start=t.now+timedelta(days=3),end=t.now+timedelta(days=3,hours=4))
    request=workforce.request_swap(t.doctor,a.pk,b.pk,'Synthetic reciprocal duty')
    assert request.swap_partner_id and ShiftCover.objects.count()==2
    with pytest.raises(ValidationError,match='Both replacement'):workforce.review_cover(request.pk,t.manager,'approved','Reviewed')
    workforce.review_cover(request.pk,t.cover,'accept','')
    workforce.review_cover(request.swap_partner_id,t.doctor,'accept','')
    workforce.review_cover(request.pk,t.manager,'approved','Both accepted and checked')
    a.refresh_from_db();b.refresh_from_db()
    assert a.staff_id==t.cover.pk and b.staff_id==t.doctor.pk
    assert set(ShiftCover.objects.values_list('status',flat=True))=={'approved'}
    client.force_login(t.doctor)
    assert client.get('/suite/workforce/new/swap/').status_code==200
    assert b'Atomic reciprocal swap' in client.get('/suite/workforce/inbox/').content


def test_missing_clock_out_independent_correction(team,client):
    t=team;a=shift(t,start=t.now-timedelta(hours=8),end=t.now+timedelta(minutes=1))
    attendance=Attendance.objects.create(shift=a,staff=t.doctor,clock_in=t.now-timedelta(hours=8),created_by=t.doctor)
    a.ends_at=t.now-timedelta(hours=1);a.save()
    correction=workforce.request_correction(attendance.pk,t.doctor,t.now-timedelta(hours=8),t.now-timedelta(hours=1),30,'Forgot clock-out; signed duty log')
    with pytest.raises(PermissionDenied):workforce.review_correction(correction.pk,t.doctor,'approved','Self')
    workforce.review_correction(correction.pk,t.manager,'approved','Checked actual duty evidence')
    attendance.refresh_from_db();assert attendance.clock_out and workforce.attendance_totals(attendance)['worked_minutes']==390
    assert attendance.history.filter(clock_out__isnull=True).exists()
    client.force_login(t.doctor);assert client.get('/suite/workforce/timesheets/').status_code==200


@pytest.mark.django_db(transaction=True)
def test_logo_validation_print_brand_and_selected_scope(client,team,settings):
    settings.MEDIA_ROOT=str(__import__('tempfile').mkdtemp())
    t=team;t.manager.role='admin';t.manager.save()
    conf=FacilityConfiguration.objects.create(facility=t.f,service_type='hospital',display_name='Scoped facility',enabled_services=['patients','billing'],configured_by=t.manager)
    client.force_login(t.manager)
    image=io.BytesIO();Image.new('RGB',(24,24),'navy').save(image,format='PNG')
    data={'facility':t.f.pk,'service_type':'custom','display_name':'Scoped facility','enabled_services':['patients','billing'],'revision':1,'receipt_paper':'80mm','print_footer':'Thank you','logo':SimpleUploadedFile('incorrect.jpg',image.getvalue(),content_type='image/png')}
    assert client.post('/accounts/setup/',data).status_code==302
    conf.refresh_from_db();assert conf.receipt_paper=='80mm' and conf.logo.name.endswith('.png')
    response=client.get(f'/accounts/branding/{t.f.pk}/logo/');assert response.status_code==200 and response['Content-Type']=='image/png'
    assert b''.join(response.streaming_content)==image.getvalue()
    # Closing a real stream emits request_finished and closes its DB connection.
    # Use committed fixtures rather than retaining pytest's enclosing transaction.
    response.close()
    from apps.billing.models import Invoice
    patient=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Invoice',gender='F')
    invoice=Invoice.objects.create(patient=patient)
    response=client.get(f'/billing/invoices/{invoice.pk}/print')
    # Use the named route to avoid coupling to the legacy URL spelling.
    from django.urls import reverse
    response=client.get(reverse('invoice-print',args=[invoice.pk]))
    assert response.status_code==200 and b'data:image/png;base64' in response.content and b'Thank you' in response.content
    client.force_login(t.outsider);assert client.get(f'/accounts/branding/{t.f.pk}/logo/').status_code==404


def test_equipment_booking_conflicts_and_approved_patient_instructions(client,team):
    from apps.orders.models import Order
    from apps.operations.models import ServiceRoom, FacilityAsset, DiagnosticTemplate, DiagnosticWorkItem
    from apps.operations.diagnostic_services import schedule, start
    t=team;patient,grant,token=patient_link(t,['instructions'])
    room=ServiceRoom.objects.create(facility=t.f,name='Synthetic imaging room',directions='First floor, room 3')
    asset=FacilityAsset.objects.create(facility=t.f,tag='TEST-SCAN',name='Synthetic scanner',location='Room 3',custodian=t.manager,created_by=t.manager)
    template=DiagnosticTemplate.objects.create(facility=t.f,name='Approved test instructions',version=1,order_type='imaging',fields=[{'key':'finding','label':'Finding','type':'text'}],patient_instructions='Synthetic instructions supplied by the facility reviewer.',instruction_language='English',instruction_reference='Approved SOP TEST-1',status='published',created_by=t.manager,reviewed_by=t.manager2)
    order=Order.objects.create(patient=patient,order_type='imaging',code='TEST-SCAN')
    when=t.now+timedelta(days=1)
    work=schedule(order.pk,t.doctor,t.doctor,'Test',when,'Recorded approved reference',1,room=room,asset=asset,instruction_template=template)
    other=Patient.objects.create(facility=t.f,first_name='Other',last_name='Synthetic',gender='M')
    other_order=Order.objects.create(patient=other,order_type='imaging',code='TEST-SCAN')
    with pytest.raises(ValidationError,match='overlapping'):schedule(other_order.pk,t.cover,t.cover,'Test',when,'',1,room=room,asset=asset)
    assert not DiagnosticWorkItem.objects.filter(order=other_order).exists()
    with pytest.raises(ValidationError,match='diagnostic booking'):Appointment.objects.create(patient=other,clinician=t.cover,room=room,scheduled_for=when)
    response=client.get('/portal/'+token)
    assert b'Approved SOP TEST-1' in response.content and b'First floor' in response.content
    assert client.post(f'/portal/{token}/instructions/{work.pk}/acknowledge/',{'revision':work.revision}).status_code==302
    work.refresh_from_db();assert work.instructions_acknowledged_grant_id==grant.pk
    asset.status='out_of_service';asset.save()
    with pytest.raises(ValidationError,match='unavailable'):start(order.pk,t.doctor)
    client.force_login(t.doctor)
    assert b'Approved SOP TEST-1' in client.get(f'/suite/diagnostics/orders/{order.pk}/').content
    assert b'First floor' in client.get(f'/suite/patient/{patient.pk}/itinerary/').content


def test_instruction_acknowledgment_rejects_changed_revision_and_other_patient(client,team):
    from apps.orders.models import Order
    from apps.operations.models import DiagnosticWorkItem
    patient,grant,token=patient_link(team,['instructions'])
    order=Order.objects.create(patient=patient,order_type='imaging',code='TEST')
    work=DiagnosticWorkItem.objects.create(order=order,instructions_snapshot={'text':'Approved test text'},created_by=team.doctor)
    assert client.post(f'/portal/{token}/instructions/{work.pk}/acknowledge/',{'revision':99}).status_code==403
    other,other_grant,other_token=patient_link(team,['instructions'])
    assert client.post(f'/portal/{other_token}/instructions/{work.pk}/acknowledge/',{'revision':1}).status_code==404
    work.refresh_from_db();assert not work.instructions_acknowledged_at


def test_module_disabled_portal_sections_are_hidden(client,team):
    patient,grant,token=patient_link(team,['billing','appointments','results','instructions','feedback'])
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Only outpatient',enabled_services=['patients','clinical'],configured_by=team.manager)
    response=client.get('/portal/'+token)
    assert response.status_code==200
    for label in (b'Invoices',b'Request an appointment',b'Diagnostic Results',b'Upcoming bookings',b'Send feedback'):
        assert label not in response.content


def test_expense_report_respects_disabled_billing_module(client,team):
    from apps.billing.models import Invoice,Payment
    patient=Patient.objects.create(facility=team.f,first_name='Synthetic',last_name='Billing disabled',gender='F')
    invoice=Invoice.objects.create(patient=patient,total_amount=1000)
    Payment.objects.create(invoice=invoice,amount=600)
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Expense management',enabled_services=['patients','management'],configured_by=team.manager)
    client.force_login(team.manager)
    response=client.get('/suite/management/expenses/report/')
    assert response.status_code==200 and response.context['collected']==0
    assert b'Billing is disabled' in response.content and b'Net of these recorded flows' not in response.content
    day=timezone.localdate().isoformat()
    response=client.get('/suite/management/expenses/report/',{'start':day,'end':day,'source':'collections'})
    assert response.context['form'].errors and response.context['page'].paginator.count==0


def test_discharge_copy_has_visible_entry_and_scope(client,team):
    from apps.operations.models import Bed, Admission
    t=team;patient=Patient.objects.create(facility=t.f,first_name='Discharged',last_name='Synthetic',gender='M')
    bed=Bed.objects.create(facility=t.f,ward='Synthetic',name='Bed 1')
    admission=Admission.objects.create(patient=patient,bed=bed,reason='Synthetic admission',created_by=t.doctor,discharged_at=t.now,discharge_summary='Clinician supplied discharge instructions.')
    client.force_login(t.doctor)
    assert b'Clinician supplied discharge instructions.' in client.get(f'/suite/admissions/{admission.pk}/discharge-copy/').content
    assert b'Print discharge and follow-up copy' in client.get('/suite/admissions/').content
    client.force_login(t.reception)
    assert client.get(f'/suite/admissions/{admission.pk}/discharge-copy/').status_code in (403,404)
