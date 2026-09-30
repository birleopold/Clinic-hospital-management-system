import pytest
from django.utils import timezone
from apps.accounts.models import FacilityConfiguration,User
from apps.demographics.models import Patient
from common.service_policy import PRESETS
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


def pharmacy(t):
    t.manager.role='admin';t.manager.save()
    return FacilityConfiguration.objects.create(facility=t.f,service_type='pharmacy',display_name='Synthetic Pharmacy',enabled_services=PRESETS['pharmacy'],configured_by=t.manager)


def test_pharmacy_home_hides_disabled_services_and_blocks_routes(client,team):
    t=team;pharmacy(t);client.force_login(t.manager)
    response=client.get('/suite/');assert response.status_code==200
    html=response.content.decode()
    assert 'Synthetic Pharmacy' in html and 'Dispensing baskets' in html
    for href in ['/labs','/suite/pregnancies/','/suite/theatre/','/ehr','/suite/diagnostics/','/suite/workforce/']:
        assert f'href="{href}"' not in html
        assert client.get(href).status_code==404
    patient=Patient.objects.create(first_name='Synthetic',last_name='Customer',gender='F',facility=t.f)
    response=client.get(f'/suite/patient/{patient.pk}/')
    assert response.status_code==200
    assert not response.context['clinical'] and not response.context['laboratory']
    assert 'maternity' not in dict(response.context['sections'])


def test_staff_navigation_has_no_admin_or_unrelated_links(client,team):
    t=team;pharmacy(t);t.nurse.role='pharmacy';t.nurse.save();client.force_login(t.nurse)
    html=client.get('/suite/').content.decode()
    assert 'Dispensing baskets' in html
    for href in ['/suite/setup/','/accounts/staff/','/suite/management/','/cashier','/ehr','/labs']:
        assert f'href="{href}"' not in html
    assert client.get('/accounts/setup/').status_code==403
    assert client.get('/accounts/staff/').status_code==403


def test_setup_dependencies_scope_and_stale_update(client,team):
    t=team;conf=pharmacy(t);client.force_login(t.manager)
    payload={'facility':t.f.pk,'service_type':'pharmacy','display_name':'Updated pharmacy','enabled_services':['pharmacy'],'revision':1}
    response=client.post('/accounts/setup/',payload)
    assert response.status_code==200 and b'supporting services' in response.content
    payload['enabled_services']=PRESETS['pharmacy']
    assert client.post('/accounts/setup/',payload).status_code==302
    conf.refresh_from_db();assert conf.revision==2 and conf.display_name=='Updated pharmacy'
    assert client.post('/accounts/setup/',payload).status_code==200
    payload['facility']=t.other.pk;payload['revision']=0
    assert client.post('/accounts/setup/',payload).status_code==200
    assert not FacilityConfiguration.objects.filter(facility=t.other).exists()


def test_staff_recruitment_scoped_roles_and_no_owner_escalation(client,team):
    t=team;pharmacy(t);client.force_login(t.manager)
    payload={'facility':t.f.pk,'username':'new-pharmacist','first_name':'Synthetic','last_name':'Pharmacist','role':'pharmacy','password':'Test-strong-password-473!', 'is_superuser':'on'}
    response=client.post('/accounts/staff/',payload)
    assert response.status_code==302,response.content[:1000]
    user=User.objects.get(username='new-pharmacist')
    assert user.staff_profile.facility_id==t.f.pk and not user.is_superuser and not user.is_staff
    assert user.check_password('Test-strong-password-473!')
    assert client.post(f'/accounts/staff/{user.pk}/',{'role':'cashier','is_active':'on','reason':'Role transfer'}).status_code==302
    assert client.post(f'/accounts/staff/{t.outsider.pk}/',{'role':'admin','is_active':'on','reason':'Try'}).status_code==404
    assert client.post(f'/accounts/staff/{t.manager.pk}/',{'role':'reception','reason':'Self'}).status_code==200


def test_mixed_diagnostics_reject_disabled_order_types_in_ui_and_api(client,team):
    from apps.orders.models import Order
    from apps.encounters.models import Encounter
    from rest_framework_simplejwt.tokens import RefreshToken
    t=team;t.manager.role='admin';t.manager.save()
    FacilityConfiguration.objects.create(facility=t.f,service_type='clinic',display_name='Clinic without laboratory',enabled_services=['patients','clinical','imaging','billing'],configured_by=t.manager)
    patient=Patient.objects.create(first_name='Synthetic',last_name='Order',gender='F',facility=t.f)
    lab=Order.objects.create(patient=patient,order_type='lab',code='HISTORIC-LAB',billable=False)
    image=Order.objects.create(patient=patient,order_type='imaging',code='IMAGE',billable=False)
    client.force_login(t.manager)
    response=client.get('/suite/diagnostics/')
    assert list(response.context['page'])==[image]
    payload={'patient':patient.pk,'order_type':'lab','code':'BLOCKED','billable':False}
    assert client.post('/api/orders/',payload).status_code==400
    assert client.get(f'/api/orders/{lab.pk}/').status_code==404
    client.logout();jwt=str(RefreshToken.for_user(t.manager).access_token)
    assert client.get('/api/inventory/items/',HTTP_AUTHORIZATION='Bearer '+jwt).status_code==403


def test_initial_setup_required_without_exposing_disabled_home(client,team,settings):
    settings.REQUIRE_SERVICE_SETUP=True
    t=team;t.manager.role='admin';t.manager.save();client.force_login(t.manager)
    assert client.get('/suite/').url=='/accounts/setup/'
    assert client.get('/accounts/setup/').status_code==200
    assert client.get('/labs').status_code==404
    t.manager.is_superuser=True;t.manager.save()
    assert client.get('/suite/').url=='/accounts/control/'
    assert client.get('/accounts/control/').status_code==200


def test_visible_home_links_are_accessible_for_pharmacy_roles(client,team):
    from html.parser import HTMLParser
    from urllib.parse import urlsplit
    t=team;pharmacy(t)
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.links=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':
                href=dict(attrs).get('href','')
                if href.startswith('/') and not href.startswith('//'):self.links.append(href)
    for actor in [t.manager,t.manager2,t.reception]:
        client.force_login(actor);parser=Links();parser.feed(client.get('/suite/').content.decode())
        for href in set(parser.links):
            response=client.get(href)
            assert response.status_code in (200,302),f'{actor.role}: {href}: {response.status_code}'
