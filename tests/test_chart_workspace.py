import pytest
from django.utils import timezone
from django.urls import reverse
from apps.accounts.models import Facility, User, StaffProfile
from apps.demographics.models import Patient
from apps.encounters.models import Encounter, Vital
from apps.orders.models import Order, OrderResult
from apps.operations.models import ClinicalEntry
from tests.test_suite import suite

pytestmark=pytest.mark.django_db


def records(s):
    visit=Encounter.objects.create(patient=s.p,clinician=s.u,chief_complaint='Synthetic complaint')
    Vital.objects.create(encounter=visit,temperature_c='36.5',weight_kg='60')
    ClinicalEntry.objects.create(patient=s.p,kind='note',text='Confidential note sentinel',created_by=s.u)
    order=Order.objects.create(patient=s.p,encounter=visit,order_type='lab',code='TEST')
    OrderResult.objects.create(order=order,result_text='Released result sentinel',approved_at=timezone.now())
    OrderResult.objects.create(order=order,result_text='Draft result sentinel')
    return visit


def test_chart_merges_sources_and_visit_filter(suite):
    visit=records(suite)
    url=reverse('suite-patient',args=[suite.p.pk])
    response=suite.client.get(url)
    assert response.status_code==200
    assert response.context['page'].paginator.count==6
    assert b'Confidential note sentinel' in response.content
    assert b'no-store' in response.headers['Cache-Control'].encode()
    response=suite.client.get(url,{'visit':visit.pk})
    assert response.context['page'].paginator.count==4
    assert b'Confidential note sentinel' not in response.content
    other=Patient.objects.create(first_name='Other',last_name='Identity',gender='F',facility=suite.f)
    other_visit=Encounter.objects.create(patient=other)
    assert suite.client.get(url,{'visit':other_visit.pk}).status_code==404


@pytest.mark.parametrize('role',['clinician','nurse','lab','pharmacy','cashier','reception','manager','store'])
def test_chart_role_boundaries(suite,role):
    records(suite)
    suite.u.role=role;suite.u.save()
    response=suite.client.get(reverse('suite-patient',args=[suite.p.pk]))
    if role in ('cashier','reception','manager','store'):
        assert response.status_code==403
        return
    assert response.status_code==200
    assert (b'Confidential note sentinel' in response.content)==(role in ('clinician','nurse'))
    assert (b'Draft result sentinel' in response.content)==(role=='lab')
    if role in ('pharmacy','lab'):
        assert suite.client.get(reverse('suite-patient',args=[suite.p.pk]),{'section':'notes'}).status_code==403
        assert suite.client.get(reverse('suite-patient-history',args=[suite.p.pk])).status_code==403


def test_chart_scopes_search_and_records(suite):
    other_facility=Facility.objects.create(name='Other clinic')
    other=Patient.objects.create(first_name='Outside',last_name='Facility',gender='M',facility=other_facility)
    assert suite.client.get(reverse('suite-patient',args=[other.pk])).status_code==404
    assert suite.client.get(reverse('suite-patient-search'),{'q':'Outside'}).context['page'].paginator.count == 0
    response=suite.client.get(reverse('suite-patient-search'),{'q':str(suite.p.medical_record_id)})
    assert response.context['page'].paginator.count==1
    StaffProfile.objects.filter(user=suite.u).update(facility=None)
    assert suite.client.get(reverse('suite-patient',args=[suite.p.pk])).status_code==404


def test_chart_pagination_and_contextual_note(suite):
    for n in range(30):ClinicalEntry.objects.create(patient=suite.p,kind='note',text=f'Note {n}',created_by=suite.u)
    url=reverse('suite-patient',args=[suite.p.pk])
    response=suite.client.get(url,{'section':'notes','page':2})
    assert len(response.context['events'])==5
    form=suite.client.get('/suite/clinical/',{'patient':suite.p.pk}).context['form']
    assert form.initial['patient']==suite.p.pk
    assert suite.client.get('/suite/clinical/',{'patient':'invalid'}).status_code==404


def test_clinician_home_only_lists_assigned_visits(suite):
    visit=records(suite)
    other=User.objects.create_user(username='other-clinician',role='clinician')
    Encounter.objects.create(patient=suite.p,clinician=other,chief_complaint='Other assignment')
    suite.u.role='clinician';suite.u.save()
    response=suite.client.get('/suite/')
    assert [v.pk for v in response.context['visits']]==[visit.pk]
    assert b'Other assignment' not in response.content


@pytest.mark.parametrize('role',['reception','clinician','nurse','pharmacy','lab','cashier','manager','store'])
def test_role_home_actions_resolve_and_are_accessible(suite,role):
    suite.u.role=role;suite.u.save()
    response=suite.client.get('/suite/')
    assert response.status_code==200
    for action in response.context['role_actions']:
        assert suite.client.get(action['url']).status_code in (200,302), (role,action)
