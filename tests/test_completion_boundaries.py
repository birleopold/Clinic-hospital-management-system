"""Boundary regressions for direct actions, not just visible home-page links."""
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts import approval_services, setup_views
from apps.accounts.models import OwnerSupportReceipt, User, FacilityConfiguration, ApprovalPolicy
from apps.demographics.models import Patient
from apps.operations.models import WorkTask, PatientDocument, Vaccination
from apps.orders.models import Order, OrderResult
from common.service_policy import can_open, PRESETS
from tests.test_workforce import team

pytestmark = pytest.mark.django_db


@pytest.fixture
def temporary_support(client):
    actor = User.objects.create_user('temporary-support', role='admin', is_superuser=True, is_staff=True)
    actor.set_unusable_password()
    actor.save()
    receipt = OwnerSupportReceipt.objects.create(
        nonce=uuid.uuid4(), user=actor, owner_reference='synthetic-owner',
        reason='Investigate synthetic issue', expires_at=timezone.now()+timedelta(minutes=30),
    )
    client.force_login(actor)
    session=client.session
    session['owner_support_receipt']=receipt.pk
    session.save()
    return actor


def test_support_cannot_create_or_promote_permanent_users(client, team, temporary_support):
    actor=temporary_support
    before=User.objects.count()
    payload={'facility':team.f.pk, 'username':'persistent-escape', 'first_name':'Synthetic',
             'last_name':'Account', 'role':'admin', 'password':'Synthetic-Strong-Password-2026'}
    assert client.post('/accounts/staff/',payload).status_code==403
    assert client.post(f'/accounts/staff/{team.nurse.pk}/',
                       {'role':'admin','is_active':'on','reason':'Unauthorized promotion'}).status_code==403
    assert User.objects.count()==before
    team.nurse.refresh_from_db()
    assert team.nurse.role=='nurse'
    for path in ['/accounts/staff/',f'/accounts/staff/{team.nurse.pk}/','/accounts/approvals/','/admin/']:
        assert not can_open(actor,path)
        assert client.get(path).status_code==403
    # Endpoint defense survives direct invocation without runtime middleware.
    request=RequestFactory().post('/accounts/staff/',payload)
    request.user=actor
    with pytest.raises(PermissionDenied):setup_views.staff(request)
    with pytest.raises(PermissionDenied):setup_views.staff_access(request,team.nurse.pk)
    assert not User.objects.filter(username='persistent-escape').exists()


def test_support_cannot_disable_approval_policy_at_service_boundary(team, temporary_support):
    policy=ApprovalPolicy.objects.create(facility=team.f,operation='purchase',enabled=True)
    with pytest.raises(PermissionDenied):
        approval_services.configure(temporary_support,team.f.pk,'purchase',False,policy.revision,'Bypass')
    policy.refresh_from_db()
    assert policy.enabled
    with pytest.raises(PermissionDenied):approval_services.administrator(temporary_support)


def test_disabled_clinical_service_blocks_patient_subroute_get_and_post(client,team):
    FacilityConfiguration.objects.create(facility=team.f,service_type='pharmacy',
        display_name='Synthetic Pharmacy',enabled_services=PRESETS['pharmacy'],configured_by=team.manager)
    patient=Patient.objects.create(first_name='Synthetic',last_name='Customer',gender='F',facility=team.f)
    client.force_login(team.doctor)
    for suffix in ('history','document'):
        url=f'/suite/patient/{patient.pk}/{suffix}/'
        assert not can_open(team.doctor,url)
        assert client.get(url).status_code==404
        assert client.post(url,{'title':'Blocked','file':SimpleUploadedFile('record.pdf',b'%PDF-1.4\n')}).status_code==404
    assert not PatientDocument.objects.exists()


def test_specialty_follow_up_does_not_leak_disabled_groups(client,team):
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Maternity clinic',
        enabled_services=['patients','clinical','maternity'],configured_by=team.manager)
    patient=Patient.objects.create(first_name='Synthetic',last_name='Specialty',gender='F',facility=team.f)
    Vaccination.objects.create(patient=patient,vaccine='Disabled vaccine sentinel',dose_label='Record only',
        due_on=timezone.localdate(),created_by=team.doctor)
    client.force_login(team.nurse)
    response=client.get('/suite/specialty-follow-up/')
    assert response.status_code==200
    assert [group['slug'] for group in response.context['groups']]==['maternity-visits']
    assert b'Disabled vaccine sentinel' not in response.content
    assert b'Vaccinations due' not in response.content


def test_radiology_can_receive_resolve_and_create_scoped_handoffs(client,team):
    team.nurse.role='radiology'
    team.nurse.save()
    task=WorkTask.objects.create(facility=team.f,audience='radiology',owner=team.nurse,
        title='Review imaging handoff',instruction='Synthetic next action',due_at=timezone.now(),created_by=team.doctor)
    hidden=WorkTask.objects.create(facility=team.other,audience='radiology',owner=team.nurse,
        title='Other site task',due_at=timezone.now(),created_by=team.outsider)
    client.force_login(team.nurse)
    home=client.get('/suite/')
    assert b'href="/suite/tasks/"' in home.content
    assert b'Review imaging handoff' in home.content
    assert client.get('/suite/tasks/').status_code==200
    assert client.get(f'/suite/tasks/{hidden.pk}/').status_code==404
    response=client.post(f'/suite/tasks/{task.pk}/',{'revision':1,'owner':team.nurse.pk,
        'status':'completed','resolution':'Synthetic review completed'})
    assert response.status_code==302
    task.refresh_from_db()
    assert task.status=='completed' and task.resolved_at
    form=client.get('/suite/tasks/new/').context['form']
    assert 'radiology' in dict(form.fields['audience'].choices)
    assert team.nurse in form.fields['owner'].queryset
    # Task access does not confer access to unrelated full patient charts.
    patient=Patient.objects.create(first_name='Synthetic',last_name='Patient',gender='F',facility=team.f)
    assert client.get(f'/suite/patient/{patient.pk}/').status_code==403


def test_nurse_cannot_download_unreleased_result_even_with_known_id(client,team,settings,tmp_path):
    settings.MEDIA_ROOT=tmp_path
    patient=Patient.objects.create(first_name='Synthetic',last_name='Result',gender='F',facility=team.f)
    order=Order.objects.create(patient=patient,order_type='lab',code='SYNTHETIC',billable=False)
    result=OrderResult.objects.create(order=order,attachment=SimpleUploadedFile('result.pdf',b'%PDF-1.4\nSynthetic'))
    client.force_login(team.nurse)
    url=f'/suite/results/{result.pk}/download/'
    assert client.get(url).status_code==404
    result.approved_at=timezone.now()
    result.save()
    response=client.get(url)
    assert response.status_code==200
    assert b'Synthetic' in b''.join(response.streaming_content)
    result.approved_at=None
    result.save()
    team.nurse.role='lab'
    team.nurse.save()
    assert client.get(url).status_code==200


def test_diagnostic_template_form_rejects_disabled_type(client,team):
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Imaging site',
        enabled_services=['patients','imaging'],configured_by=team.manager)
    client.force_login(team.doctor)
    form=client.get('/suite/diagnostics/templates/new/').context['form']
    assert [(key,label) for key,label in form.fields['order_type'].choices if key]==[('imaging','Imaging')]
    assert not form.fields['order_type'].valid_value('lab')
    assert not form.fields['order_type'].valid_value('procedure')


def test_role_changes_and_deactivation_require_task_reassignment(client,team):
    team.manager.role='admin'
    team.manager.save()
    task=WorkTask.objects.create(facility=team.f,audience='nurse',owner=team.nurse,
        title='Owned work',due_at=timezone.now(),created_by=team.doctor)
    client.force_login(team.manager)
    url=f'/accounts/staff/{team.nurse.pk}/'
    for payload in ({'role':'nurse','reason':'End access'},
                    {'role':'clinician','is_active':'on','reason':'Change role'}):
        response=client.post(url,payload)
        assert response.status_code==200 and b'Reassign' in response.content
        team.nurse.refresh_from_db()
        assert team.nurse.role=='nurse' and team.nurse.is_active
    task.owner=team.doctor
    task.save()
    assert client.post(url,{'role':'nurse','reason':'Reassigned work; end access'}).status_code==302
    team.nurse.refresh_from_db()
    assert not team.nurse.is_active


def test_lab_screen_cannot_write_or_cancel_disabled_imaging(client,team):
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Lab site',
        enabled_services=['patients','lab'],configured_by=team.manager)
    patient=Patient.objects.create(first_name='Synthetic',last_name='Order',gender='F',facility=team.f)
    lab=Order.objects.create(patient=patient,order_type='lab',code='VISIBLE-LAB',billable=False)
    imaging=Order.objects.create(patient=patient,order_type='imaging',code='DISABLED-IMAGE',billable=False)
    client.force_login(team.doctor)
    response=client.get('/labs')
    assert response.status_code==200 and list(response.context['pending_orders'])==[lab]
    assert client.post('/labs/submit',{'order_id':imaging.pk,'result_text':'Blocked'}).status_code==404
    assert client.post(f'/orders/{imaging.pk}/cancel').status_code==404
    assert not OrderResult.objects.filter(order=imaging).exists()
    imaging.refresh_from_db()
    assert imaging.status=='ordered'


def test_insights_sources_exclude_disabled_services(client,team):
    from apps.appointments.models import QueueTicket
    FacilityConfiguration.objects.create(facility=team.f,service_type='custom',display_name='Management site',
        enabled_services=['patients','management'],configured_by=team.manager)
    patient=Patient.objects.create(first_name='Synthetic',last_name='Metrics',gender='F',facility=team.f)
    QueueTicket.objects.create(patient=patient,service='lab')
    Order.objects.create(patient=patient,order_type='lab',code='DISABLED',billable=False)
    client.force_login(team.manager)
    for kind in ('queue','orders','claims'):
        response=client.get('/suite/insights/',{'kind':kind})
        assert response.status_code==200
        assert response.context['page'].paginator.count==0
        assert response.context['waits']==[] and response.context['turnaround']==[]
