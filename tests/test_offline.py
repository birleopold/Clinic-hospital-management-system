import copy
import json
import uuid
import pytest
from django.test import Client
from django.utils import timezone
from apps.accounts.models import Facility, User, StaffProfile
from apps.demographics.models import Patient
from apps.operations.models import ClinicalEntry, OfflineDevice, OfflineReceipt
from tests.test_suite import suite

pytestmark = pytest.mark.django_db


def post(client, path, data):
    return client.post(
        "/offline/api/" + path, data=json.dumps(data), content_type="application/json"
    )


def prepare(suite, client=None):
    client = client or suite.client
    response = post(client, "devices/", {"label": "Synthetic device"})
    assert response.status_code == 201
    device = response.json()["device_id"]
    response = post(
        client, "prepare/", {"device_id": device, "patient_ids": [suite.p.pk]}
    )
    assert response.status_code == 200, response.content
    return device, response.json()


def draft(device, pack, patient, text="Synthetic offline note"):
    schema = next(s for s in pack["schemas"] if s["slug"] == "clinical")
    relation = next(f for f in schema["fields"] if f["name"] == "patient")
    choice = next(c for c in relation["choices"] if c["value"] == str(patient.pk))
    return {
        "device_id": device,
        "client_id": str(uuid.uuid4()),
        "client_created_at": timezone.now().isoformat(),
        "slug": "clinical",
        "grant": pack["grant"],
        "values": {
            "patient": str(patient.pk),
            "kind": "note",
            "text": text,
            "supersedes": "",
        },
        "proofs": {"patient": choice["proof"]},
    }


def test_offline_draft_sync_is_idempotent_and_append_only(suite):
    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    first = post(suite.client, "sync/", payload)
    second = post(suite.client, "sync/", payload)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["record_id"] == second.json()["record_id"]
    assert ClinicalEntry.objects.count() == 1 and OfflineReceipt.objects.count() == 1
    payload["values"]["text"] = "Changed content under same submission ID"
    assert post(suite.client, "sync/", payload).status_code == 409
    assert ClinicalEntry.objects.get().text == "Synthetic offline note"


def test_two_devices_can_append_without_overwriting_each_other(suite):
    first, pack1 = prepare(suite)
    second, pack2 = prepare(suite)
    assert (
        post(
            suite.client, "sync/", draft(first, pack1, suite.p, "Device one")
        ).status_code
        == 201
    )
    assert (
        post(
            suite.client, "sync/", draft(second, pack2, suite.p, "Device two")
        ).status_code
        == 201
    )
    assert set(ClinicalEntry.objects.values_list("text", flat=True)) == {
        "Device one",
        "Device two",
    }


def test_changed_patient_blocks_stale_offline_context(suite):
    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    suite.p.allergy_status = "recorded"
    suite.p.save()
    response = post(suite.client, "sync/", payload)
    assert response.status_code == 409 and response.json()["conflict"]
    assert not ClinicalEntry.objects.exists() and not OfflineReceipt.objects.exists()


def test_revocation_and_account_change_block_sync(suite):
    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    colleague = User.objects.create_user(username="other-clinician", role="clinician")
    StaffProfile.objects.update_or_create(
        user=colleague, defaults={"facility": suite.f}
    )
    suite.client.force_login(colleague)
    assert post(suite.client, "sync/", payload).status_code == 403
    suite.client.force_login(suite.u)
    assert post(suite.client, "devices/", {"revoke": device}).status_code == 200
    assert post(suite.client, "sync/", payload).status_code == 403
    assert not ClinicalEntry.objects.exists()


def test_offline_preparation_cannot_download_other_facility(suite):
    device, _ = prepare(suite)
    other = Facility.objects.create(name="Other")
    foreign = Patient.objects.create(
        first_name="Secret", last_name="Patient", gender="F", facility=other
    )
    assert (
        post(
            suite.client, "prepare/", {"device_id": device, "patient_ids": [foreign.pk]}
        ).status_code
        == 403
    )
    assert (
        suite.client.get("/offline/api/patients/", {"q": "Secret"}).json()["patients"]
        == []
    )


def test_tampered_proofs_and_unsupported_transactions_are_rejected(suite):
    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    invalid = copy.deepcopy(payload)
    invalid["proofs"]["patient"] = "tampered"
    assert post(suite.client, "sync/", invalid).status_code == 409
    invalid = copy.deepcopy(payload)
    invalid["slug"] = "collections"
    assert post(suite.client, "sync/", invalid).status_code == 403
    invalid = copy.deepcopy(payload)
    invalid["values"]["approved_by"] = "1"
    assert post(suite.client, "sync/", invalid).status_code == 422
    assert not OfflineReceipt.objects.exists()


def test_offline_api_requires_csrf_and_does_not_cache_patient_context(suite):
    client = Client(enforce_csrf_checks=True)
    client.force_login(suite.u)
    assert post(client, "devices/", {"label": "No CSRF"}).status_code == 403
    info = client.get("/offline/api/session/")
    token = info.json()["csrf"]
    response = client.post(
        "/offline/api/devices/",
        data=json.dumps({"label": "CSRF device"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert (
        response.status_code == 201 and response["Cache-Control"] == "private, no-store"
    )
    shell = client.get("/offline/")
    assert suite.p.first_name.encode() not in shell.content
    assert "script-src 'self'" in shell["Content-Security-Policy"]


def test_expired_snapshot_needs_refresh_but_successful_retry_is_safe(
    suite, monkeypatch
):
    import time

    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    assert post(suite.client, "sync/", payload).status_code == 201
    later = time.time() + 8 * 24 * 60 * 60
    monkeypatch.setattr("django.core.signing.time.time", lambda: later)
    assert post(suite.client, "sync/", payload).status_code == 200
    payload["client_id"] = str(uuid.uuid4())
    assert post(suite.client, "sync/", payload).status_code == 409
    assert ClinicalEntry.objects.count() == 1


def test_invalid_draft_does_not_create_receipt(suite):
    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    payload["values"]["text"] = ""
    result = post(suite.client, "sync/", payload)
    assert result.status_code == 422 and "text" in result.json()["fields"]
    assert not OfflineReceipt.objects.exists()


def test_facility_admin_can_revoke_colleagues_device(suite):
    colleague = User.objects.create_user(username="device-colleague", role="clinician")
    StaffProfile.objects.update_or_create(
        user=colleague, defaults={"facility": suite.f}
    )
    suite.client.force_login(colleague)
    device = post(suite.client, "devices/", {"label": "Lost tablet"}).json()[
        "device_id"
    ]
    suite.client.force_login(suite.u)
    listed = suite.client.get("/offline/api/devices/", {"facility": "1"}).json()[
        "devices"
    ]
    assert any(d["id"] == device for d in listed)
    assert post(suite.client, "devices/", {"revoke": device}).status_code == 200
    assert OfflineDevice.objects.get(pk=device).revoked_at


def test_offline_receipt_preserves_device_and_server_times(suite):
    from datetime import timedelta

    device, pack = prepare(suite)
    payload = draft(device, pack, suite.p)
    authored = timezone.now() - timedelta(hours=2)
    payload["client_created_at"] = authored.isoformat()
    assert post(suite.client, "sync/", payload).status_code == 201
    receipt = OfflineReceipt.objects.get()
    assert receipt.client_created_at == authored and receipt.created_at > authored
    later = draft(device, pack, suite.p)
    later["client_created_at"] = (timezone.now() + timedelta(days=1)).isoformat()
    assert post(suite.client, "sync/", later).status_code == 422
    assert ClinicalEntry.objects.count() == 1
