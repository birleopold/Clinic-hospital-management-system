"""Generic writes cannot bypass department-specific queue workflow actions."""
import pytest
from rest_framework.test import APIClient
from apps.appointments.models import QueueTicket
from apps.demographics.models import Patient
from tests.test_workforce import team

pytestmark=pytest.mark.django_db


@pytest.fixture
def queue(team):
    patient=Patient.objects.create(first_name='Synthetic',last_name='Queue',gender='F',facility=team.f)
    ticket=QueueTicket.objects.create(patient=patient,service='lab')
    team.nurse.role='lab';team.nurse.save()
    api=APIClient();api.force_authenticate(team.nurse)
    return team,ticket,api


@pytest.mark.parametrize('field,value', [('status','in_service'),('status','done'),('service','triage')])
def test_generic_patch_cannot_change_ticket_workflow(queue,field,value):
    team,ticket,api=queue
    response=api.patch(f'/api/queue-tickets/{ticket.pk}/',{field:value})
    assert response.status_code==400
    ticket.refresh_from_db()
    assert ticket.status=='waiting' and ticket.service=='lab' and ticket.assigned_to_id is None


def test_generic_patch_cannot_reassign_patient_or_operator(queue):
    team,ticket,api=queue
    other=Patient.objects.create(first_name='Other',last_name='Patient',gender='M',facility=team.f)
    for payload in ({'patient':other.pk},{'assigned_to':team.nurse.pk}):
        assert api.patch(f'/api/queue-tickets/{ticket.pk}/',payload).status_code==400
    ticket.refresh_from_db()
    assert ticket.patient_id!=other.pk and ticket.assigned_to_id is None


@pytest.mark.parametrize('role,expected',[('nurse',403),('clinician',403),('lab',200),('reception',200),('admin',200)])
def test_queue_note_edits_match_department_or_reception(queue,role,expected):
    team,ticket,api=queue
    team.nurse.role=role;team.nurse.save()
    assert api.patch(f'/api/queue-tickets/{ticket.pk}/',{'notes':'Synthetic update'}).status_code==expected
    ticket.refresh_from_db()
    assert bool(ticket.notes)==(expected==200)


@pytest.mark.parametrize('state',['in_service','done','cancelled'])
def test_creation_cannot_forge_completed_or_claimed_queue(queue,state):
    team,ticket,api=queue
    api.force_authenticate(team.reception)
    response=api.post('/api/queue-tickets/',{'patient':ticket.patient_id,'service':'lab','status':state})
    assert response.status_code==400
    assert QueueTicket.objects.count()==1
    assert api.post('/api/queue-tickets/',{'patient':ticket.patient_id,'service':'lab','assigned_to':team.nurse.pk}).status_code==400


def test_start_finish_are_retry_safe_and_invalid_transitions_are_client_errors(queue):
    team,ticket,api=queue
    url=f'/api/queue-tickets/{ticket.pk}/'
    assert api.post(url+'finish/').status_code==400
    assert api.post(url+'start/').status_code==200
    ticket.refresh_from_db();started=ticket.started_at
    assert api.post(url+'start/').status_code==200
    ticket.refresh_from_db()
    assert ticket.started_at==started and ticket.assigned_to_id==team.nurse.pk
    team.cover.role='lab';team.cover.save();api.force_authenticate(team.cover)
    assert api.post(url+'start/').status_code==409
    ticket.refresh_from_db()
    assert ticket.assigned_to_id==team.nurse.pk and ticket.started_at==started
    api.force_authenticate(team.nurse)
    assert api.post(url+'finish/').status_code==200
    ticket.refresh_from_db();finished=ticket.finished_at
    assert api.post(url+'finish/').status_code==200
    ticket.refresh_from_db();assert ticket.finished_at==finished
    assert api.post(url+'start/').status_code==400
    api.force_authenticate(team.reception)
    assert api.post(url+'cancel/').status_code==400


def test_cancel_is_retry_safe_and_cannot_restart(queue):
    team,ticket,api=queue
    url=f'/api/queue-tickets/{ticket.pk}/'
    api.force_authenticate(team.reception)
    assert api.post(url+'cancel/').status_code==200
    ticket.refresh_from_db();finished=ticket.finished_at
    assert api.post(url+'cancel/').status_code==200
    ticket.refresh_from_db();assert ticket.finished_at==finished
    api.force_authenticate(team.nurse)
    assert api.post(url+'start/').status_code==400
    assert api.post(url+'finish/').status_code==400


def test_wrong_department_cannot_start_or_finish(queue):
    team,ticket,api=queue
    api.force_authenticate(team.doctor)
    url=f'/api/queue-tickets/{ticket.pk}/'
    assert api.post(url+'start/').status_code==403
    assert api.post(url+'finish/').status_code==403
    ticket.refresh_from_db()
    assert ticket.status=='waiting'


@pytest.mark.django_db(transaction=True)
def test_postgres_notes_update_serializes_with_start(queue,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import connection, connections
    from apps.appointments.serializers import QueueTicketSerializer
    from apps.appointments.views import QueueTicketViewSet
    if connection.vendor!='postgresql':pytest.skip('Row-lock contention requires PostgreSQL.')
    team,ticket,_=queue
    updating=Event();release=Event();starting=Event()
    original=QueueTicketSerializer.validate
    def blocked_validation(self,attrs):
        if attrs.get('notes')=='Concurrent note':
            updating.set()
            assert release.wait(15)
        return original(self,attrs)
    monkeypatch.setattr(QueueTicketSerializer,'validate',blocked_validation)
    get_object=QueueTicketViewSet.get_object
    def signal_start_read(self):
        if self.action=='start':starting.set()
        return get_object(self)
    monkeypatch.setattr(QueueTicketViewSet,'get_object',signal_start_read)
    def write(kind):
        connections.close_all()
        try:
            api=APIClient();api.force_authenticate(team.nurse)
            if kind=='note':return api.patch(f'/api/queue-tickets/{ticket.pk}/',{'notes':'Concurrent note'}).status_code
            return api.post(f'/api/queue-tickets/{ticket.pk}/start/').status_code
        finally:connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        note=pool.submit(write,'note')
        try:
            assert updating.wait(15)
            start=pool.submit(write,'start')
            assert starting.wait(15)
            from concurrent.futures import wait
            assert not wait([start],timeout=0.1).done
        finally:release.set()
        assert note.result(timeout=15)==200
        assert start.result(timeout=15)==200
    ticket.refresh_from_db()
    assert ticket.notes=='Concurrent note' and ticket.status=='in_service'
    assert ticket.assigned_to_id==team.nurse.pk and ticket.started_at
