import uuid
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from apps.accounts.models import User, StaffProfile
from apps.demographics.models import Patient
from apps.appointments.models import QueueTicket
from apps.operations import extension_services as s, diagnostic_services as d, outreach_services as o
from apps.operations.models import (Reminder, PatientRecall, RecallOutreach, Specimen, FacilityAsset,
    ProgrammeDefinition, ProgrammeEnrollment, ProgrammeReview, LaboratoryQC, ReagentLot, ImagingStudy)
from tests.test_workforce import team
from tests.test_diagnostics_visiting import diagnostic

pytestmark=pytest.mark.django_db


def lab(t, name='lab'):
    user=User.objects.create_user(username=name,role='lab')
    StaffProfile.objects.update_or_create(user=user,defaults={'facility':t.f})
    return user


def test_current_consent_optout_idempotent_recall_and_scope(team):
    t=team;p=Patient.objects.create(first_name='Synthetic',last_name='Consent',gender='F',facility=t.f,phone='+256700000001')
    with pytest.raises(PermissionDenied):o.set_preference(p.pk,t.outsider,True,p.phone,'Evidence')
    with pytest.raises(ValidationError):o.set_preference(p.pk,t.reception,True,'wrong','Evidence')
    o.set_preference(p.pk,t.reception,True,p.phone,'Verified patient request')
    recall=PatientRecall.objects.create(patient=p,owner=t.doctor,purpose='Follow up',due_on=timezone.localdate()-timedelta(days=1),created_by=t.doctor)
    call_command('queue_due_recalls');assert not RecallOutreach.objects.exists()
    call_command('queue_due_recalls',commit=True);call_command('queue_due_recalls',commit=True)
    link=RecallOutreach.objects.get();assert link.reminder and link.escalation and Reminder.objects.count()==1
    assert o.consent_valid(link.reminder)
    o.set_preference(p.pk,t.reception,False,'','Patient opted out')
    link.reminder.refresh_from_db();assert link.reminder.status=='cancelled' and not o.consent_valid(link.reminder)


class FakeSMS:
    supports_idempotency=True
    def send(self,*args,**kwargs):return {'ok':True,'ref':'synthetic-provider-reference'}


@override_settings(INTEGRATIONS_SMS_BACKEND='tests.test_phase_three_five_extensions.FakeSMS')
def test_dispatch_attempts_uncertainty_retry_and_changed_phone(team):
    t=team;p=Patient.objects.create(first_name='Synthetic',last_name='Delivery',gender='F',facility=t.f,phone='+256700000001')
    o.set_preference(p.pk,t.reception,True,p.phone,'Verified consent')
    def job():return Reminder.objects.create(patient=p,created_by=t.reception,scheduled_for=t.now,consent_confirmed=True)
    accepted=job();call_command('dispatch_reminders');accepted.refresh_from_db()
    assert accepted.status=='sent' and accepted.delivery_attempts.get().outcome=='accepted'
    uncertain=job()
    with patch.object(FakeSMS,'send',side_effect=TimeoutError):call_command('dispatch_reminders')
    uncertain.refresh_from_db();assert uncertain.status=='failed' and uncertain.delivery_attempts.get().outcome=='review'
    with pytest.raises(ValidationError,match='Reconcile'):o.retry(uncertain.pk,t.reception)
    failed=job()
    with patch.object(FakeSMS,'send',return_value={'ok':False,'definitive_failure':True}):call_command('dispatch_reminders')
    o.retry(failed.pk,t.reception);call_command('dispatch_reminders');failed.refresh_from_db();assert failed.attempts==2 and failed.status=='sent'
    changed=job();p.phone='+256700000002';p.save();call_command('dispatch_reminders');changed.refresh_from_db();assert changed.status=='failed' and changed.attempts==0


def test_custody_continuity_aliquot_and_disposal(team):
    t=team;operator=lab(t);p,order,template=diagnostic(t,'lab')
    specimen=Specimen.objects.create(order=order,specimen_type='Synthetic blood',status='received',created_by=operator)
    data=dict(event='stored',from_location='Intake',to_location='Shelf A',receiver='Operator reference',condition='Intact',reference='REF-1',occurred_at=timezone.now())
    first=s.custody(specimen.pk,operator,**data);assert s.custody(specimen.pk,operator,**data).pk==first.pk
    with pytest.raises(ValidationError,match='different custody'):s.custody(specimen.pk,operator,**{**data,'condition':'Changed'})
    child=s.aliquot(specimen.pk,operator,1,'mL','Approved split')
    assert child.child.order_id==order.pk and child.child.status=='collected' and child.child.accession!=specimen.accession
    with pytest.raises(ValidationError,match='location'):s.custody(specimen.pk,operator,**{**data,'reference':'REF-2','occurred_at':timezone.now()})
    s.custody(specimen.pk,operator,**{**data,'event':'disposed','from_location':'Shelf A','to_location':'Disposal','reference':'REF-2','occurred_at':timezone.now()})
    with pytest.raises(ValidationError):s.aliquot(specimen.pk,operator,1,'mL','Try after disposal')
    with pytest.raises(PermissionDenied):s.custody(specimen.pk,t.reception,**data)


def test_qc_independent_review_and_release_guard(team):
    t=team;operator=lab(t);reviewer=lab(t,'lab-reviewer');p,order,template=diagnostic(t,'lab')
    reagent=s.reagent_create(operator,facility=t.f,name='Synthetic reagent',lot_number='LOT1',expires_on=timezone.localdate()+timedelta(days=10))
    with pytest.raises(ValidationError,match='Another'):s.reagent_review(reagent.pk,operator,True,'Self')
    s.reagent_review(reagent.pk,reviewer,True,'Verified supplier and storage evidence')
    asset=FacilityAsset.objects.create(facility=t.f,tag='LAB1',name='Synthetic analyzer',custodian=operator,created_by=t.manager)
    qc=s.qc_create(operator,facility=t.f,asset=asset,reagent=reagent,procedure_reference='Approved SOP reference',control_lot='CONTROL1',observations='Manual control observations',outcome='pass',valid_until=timezone.now()+timedelta(hours=1))
    with pytest.raises(ValidationError,match='Another'):s.qc_review(qc.pk,operator,'Self')
    s.qc_review(qc.pk,reviewer,'Reviewed under approved SOP')
    specimen=Specimen.objects.create(order=order,specimen_type='Synthetic sample',status='received',created_by=operator)
    sheet=d.submit(order.pk,t.doctor,template,{'findings':'Synthetic result'},uuid.uuid4(),specimen=specimen)
    s.attach_run(sheet.pk,operator,qc,timezone.now(),'RUN1')
    s.reagent_review(reagent.pk,operator,False,'Subsequent safety concern')
    with pytest.raises(ValidationError,match='unquarantined'):d.review(sheet.pk,t.cover,'release','Review')
    s.reagent_review(reagent.pk,reviewer,True,'Concern resolved with evidence')
    # Re-release after a historical run invalidates this association conservatively.
    with pytest.raises(ValidationError):d.review(sheet.pk,t.cover,'release','Review')


def test_programme_publication_snapshot_cohort_and_review_scope(team,client):
    t=team;p=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Programme',gender='F')
    definition=s.programme_create(t.doctor,facility=t.f,name='Approved local programme',version=1,clinical_owner=t.doctor,source_reference='Facility SOP 2026-01',protocol='Manual eligibility and planned follow-up')
    with pytest.raises(ValidationError,match='Another'):s.programme_review(definition.pk,t.doctor,'published','Self')
    s.programme_review(definition.pk,t.cover,'published','Approved by clinical owner review')
    data=dict(patient=p,programme=definition,clinician=t.doctor,eligibility_evidence='Assessed by clinician',consent_reference='Consent reference',enrolled_on=timezone.localdate(),next_review=timezone.localdate()+timedelta(days=30))
    enrollment=s.enroll(t.doctor,**data)
    assert 'v1' in enrollment.protocol_snapshot
    with pytest.raises(ValidationError):s.enroll(t.doctor,**data)
    s.programme_visit(enrollment.pk,t.nurse,occurred_on=timezone.localdate(),findings='Reviewed',plan='Clinician follow-up',next_review=timezone.localdate()+timedelta(days=15))
    s.programme_review(definition.pk,t.cover,'retired','Superseded locally')
    enrollment.refresh_from_db();assert 'Manual eligibility' in enrollment.protocol_snapshot
    with pytest.raises(ValidationError,match='published'):s.enroll(t.doctor,**data)
    s.programme_close(enrollment.pk,t.doctor,'transferred','Receiving service reference')
    with pytest.raises(ValidationError,match='closed'):s.programme_visit(enrollment.pk,t.nurse,occurred_on=timezone.localdate(),findings='Late',plan='Late',next_review=timezone.localdate())
    client.force_login(t.reception);assert client.get('/suite/clinical-operations/enrollments/').status_code==403
    client.force_login(t.outsider);assert client.post(f'/suite/clinical-operations/programmes/{definition.pk}/action/',{'decision':'published','reason':'Try'}).status_code==403


@override_settings(PACS_VIEWER_ALLOWED_HOSTS=['viewer.example.org'])
def test_study_links_allowlist_and_facility(team,client):
    t=team;p,order,template=diagnostic(t)
    data=dict(order=order,study_uid='1.2.840.12345',accession='ACC1',modality='CT',performed_at=timezone.now(),reference='Actual device reference')
    for url in ['http://viewer.example.org/study','https://evil.example.org/study','https://viewer.example.org@evil.example.org/study','https://viewer.example.org/study?token=secret','https://viewer.example.org:444/study']:
        with pytest.raises(ValidationError):s.imaging_create(t.doctor,viewer_url=url,**data)
    with pytest.raises(ValidationError):s.imaging_create(t.doctor,**{**data,'study_uid':'01.2'})
    study=s.imaging_create(t.doctor,viewer_url='https://viewer.example.org/study/123',**data)
    assert study.study_uid==data['study_uid']
    client.force_login(t.doctor);assert client.get('/suite/clinical-operations/studies/').status_code==200
    client.force_login(t.reception);assert client.get('/suite/clinical-operations/studies/').status_code==403


def test_all_extension_pages_and_scoped_selectors(team,client):
    from apps.operations.extension_views import REGISTERS
    t=team;t.doctor.is_superuser=True;t.doctor.save();client.force_login(t.doctor)
    for kind in REGISTERS:
        assert client.get(f'/suite/clinical-operations/{kind}/').status_code==200
        assert client.get(f'/suite/clinical-operations/{kind}/new/').status_code==200
    assert client.get('/suite/outreach/').status_code==200
    assert client.get('/suite/insights/').status_code==200
    t.doctor.is_superuser=False;t.doctor.save()
    form=client.get('/suite/clinical-operations/programmes/new/').context['form']
    assert list(form.fields['facility'].queryset)==[t.f]


def test_insight_denominators_and_scope(team,client):
    t=team;p=Patient.objects.create(facility=t.f,first_name='Synthetic',last_name='Metrics',gender='F')
    other=Patient.objects.create(facility=t.other,first_name='Other',last_name='Metrics',gender='F')
    measured=QueueTicket.objects.create(patient=p,service='consult')
    QueueTicket.objects.filter(pk=measured.pk).update(created_at=t.now-timedelta(minutes=30),started_at=t.now-timedelta(minutes=10),status='in_service')
    QueueTicket.objects.create(patient=p,service='consult')
    QueueTicket.objects.create(patient=other,service='consult')
    client.force_login(t.manager);response=client.get('/suite/insights/?days=30')
    row=next(row for row in response.context['waits'] if row[0]=='Consult')
    assert row[1:]==(2,1,1,20.0)
    assert response.context['page'].paginator.count==2
    client.force_login(t.reception);assert client.get('/suite/insights/').status_code==403
