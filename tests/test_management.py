from datetime import timedelta
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
import pytest
from apps.operations.models import ManagementCase, CorrectiveAction, FacilityAsset, AssetEvent, StaffChecklist, OperatingBudget, OperatingExpense
from apps.operations import management_services as s
from tests.test_workforce import team, shift

pytestmark=pytest.mark.django_db


def create(actor,model,**data):
    fields=list(data)
    Form=forms.modelform_factory(model,fields=fields)
    form=Form({key:value.pk if hasattr(value,'pk') else value for key,value in data.items()})
    assert form.is_valid(),form.errors
    return s.create_record(actor,form)


def test_case_resolution_requires_completed_actions_and_other_reviewer(team):
    t=team
    case=create(t.manager,ManagementCase,facility=t.f,kind='incident',severity='high',title='Synthetic equipment delay',details='Restricted details',owner=t.manager,due_at=t.now+timedelta(days=1))
    action=create(t.manager,CorrectiveAction,case=case,owner=t.manager,description='Check equipment logs',due_at=t.now+timedelta(hours=3))
    with pytest.raises(ValidationError,match='Complete corrective'):s.decide(ManagementCase,case.pk,t.manager,'resolve','Resolved',1)
    s.decide(CorrectiveAction,action.pk,t.manager,'complete','Service evidence reference')
    s.decide(ManagementCase,case.pk,t.manager,'resolve','Resolved',1)
    with pytest.raises(ValidationError,match='different supervisor'):s.decide(ManagementCase,case.pk,t.manager,'close','Checked',2)
    s.decide(ManagementCase,case.pk,t.manager2,'close','Verified',2)
    case.refresh_from_db();assert case.status=='closed' and case.history.count()==3
    with pytest.raises(PermissionDenied):s.decide(ManagementCase,case.pk,t.outsider,'reopen','Other facility',3)


def test_budget_expense_limits_and_separation(team):
    t=team;today=timezone.localdate()
    budget=create(t.manager,OperatingBudget,facility=t.f,cost_centre='Equipment',starts_on=today,ends_on=today+timedelta(days=30),amount='1000')
    with pytest.raises(ValidationError,match='different supervisor'):s.decide(OperatingBudget,budget.pk,t.manager,'approved','Self')
    s.decide(OperatingBudget,budget.pk,t.manager2,'approved','Agreed budget')
    expense=create(t.manager,OperatingExpense,budget=budget,incurred_on=today,payee='Synthetic supplier',reference='INV001',description='Service',amount='700')
    s.decide(OperatingExpense,expense.pk,t.manager2,'approved','Invoice checked')
    other=create(t.manager,OperatingExpense,budget=budget,incurred_on=today,payee='Synthetic supplier',reference='INV002',description='Service',amount='400')
    with pytest.raises(ValidationError,match='exceed'):s.decide(OperatingExpense,other.pk,t.manager2,'approved','Over budget')
    from apps.billing.models import Payment
    assert Payment.objects.count()==0


def test_assets_retain_service_history_and_downtime(team):
    t=team
    asset=create(t.manager,FacilityAsset,facility=t.f,tag='TEST001',name='Synthetic analyzer',location='Lab',custodian=t.nurse)
    create(t.manager,AssetEvent,asset=asset,kind='downtime',vendor='',cost=0,evidence='Out of service',next_due='')
    asset.refresh_from_db();assert asset.status=='out_of_service'
    create(t.manager,AssetEvent,asset=asset,kind='maintenance',vendor='Synthetic service',cost=100,evidence='Service report 001',next_due=timezone.localdate()+timedelta(days=90))
    asset.refresh_from_db();assert asset.maintenance_due and asset.status=='out_of_service'
    create(t.manager,AssetEvent,asset=asset,kind='restore',vendor='',cost=0,evidence='Passed return-to-service inspection',next_due='')
    asset.refresh_from_db();assert asset.status=='operational' and asset.events.count()==3


def test_checklist_acknowledgment_and_offboarding_guards(team):
    t=team
    item=create(t.manager,StaffChecklist,facility=t.f,staff=t.doctor,owner=t.manager,kind='policy',title='Test policy',version='v1',instructions='Review approved document reference',due_at=t.now+timedelta(days=1))
    s.decide(StaffChecklist,item.pk,t.manager,'complete','Document provided')
    with pytest.raises(ValidationError,match='acknowledgment'):s.decide(StaffChecklist,item.pk,t.manager2,'review','Checked')
    with pytest.raises(PermissionDenied):s.decide(StaffChecklist,item.pk,t.nurse,'acknowledge','Read')
    s.decide(StaffChecklist,item.pk,t.doctor,'acknowledge','Read v1')
    s.decide(StaffChecklist,item.pk,t.manager2,'review','Checked')
    off=create(t.manager,StaffChecklist,facility=t.f,staff=t.doctor,owner=t.manager,kind='offboarding',title='Exit checklist',version='',instructions='Close and reassign work',due_at=t.now+timedelta(days=1))
    s.decide(StaffChecklist,off.pk,t.manager,'complete','Prepared')
    a=shift(t)
    with pytest.raises(ValidationError,match='Reassign'):s.decide(StaffChecklist,off.pk,t.manager2,'review','Exit')
    from apps.operations.workforce_services import shift_action
    shift_action(a.pk,t.manager,'cancel',a.revision,'Exit')
    with pytest.raises(PermissionDenied):s.decide(StaffChecklist,off.pk,t.manager2,'review','Exit')
    t.manager2.role='admin';t.manager2.save()
    s.decide(StaffChecklist,off.pk,t.manager2,'review','Access removed')
    t.doctor.refresh_from_db();assert not t.doctor.is_active


def test_manager_register_scopes(client,team):
    t=team;client.force_login(t.manager)
    assert client.get('/suite/management/').status_code==200
    for kind in ['cases','actions','assets','asset-events','checklists','budgets','expenses']:
        assert client.get(f'/suite/management/{kind}/').status_code==200
        assert client.get(f'/suite/management/{kind}/new/').status_code==200
    client.force_login(t.nurse)
    assert client.get('/suite/management/checklists/').status_code==200
    assert client.get('/suite/management/cases/').status_code==403
    assert client.get('/suite/management/budgets/new/').status_code==403
