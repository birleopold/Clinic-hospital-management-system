from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.urls import reverse
from django.core.management import call_command
from django.core.management.base import CommandError
from tests.test_suite import suite
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.billing.models import Invoice, InvoiceLine, Payment
from apps.operations.models import (
    DuplicateReview,
    PatientMerge,
    PortalGrant,
    Payer,
    CoveragePlan,
    Policy,
    Claim,
    Remittance,
    PaymentIntent,
    LabPanel,
    LabAnalyte,
    Specimen,
    InpatientOrder,
    Bed,
    Admission,
    SmsDelivery,
)
from apps.operations.advanced_services import (
    merge_patients,
    prepare_claim,
    post_remittance,
    scheduled_doses,
)
from apps.operations.advanced_validation import validate_new_record
from apps.orders.models import Order, OrderResult
from apps.integrations.collections import submit_collection, reconcile_collection

pytestmark = pytest.mark.django_db


def test_merge_moves_links_preserves_source_and_history(suite):
    source = Patient.objects.create(
        first_name="Duplicate", last_name="Patient", gender="F", facility=suite.f
    )
    encounter = Encounter.objects.create(patient=source)
    invoice = Invoice.objects.create(patient=source, total_amount=20)
    review = DuplicateReview.objects.create(
        patient=suite.p,
        candidate=source,
        reason="ID verified",
        status="confirmed",
        created_by=suite.u,
    )
    grant = PortalGrant.objects.create(
        patient=source,
        created_by=suite.u,
        expires_at=timezone.now() + timedelta(days=1),
    )
    event = merge_patients(review.pk, suite.u, "Verified physical identity")
    assert merge_patients(review.pk, suite.u, "Repeated request").pk == event.pk
    encounter.refresh_from_db()
    invoice.refresh_from_db()
    source.refresh_from_db()
    grant.refresh_from_db()
    assert encounter.patient_id == suite.p.pk and invoice.patient_id == suite.p.pk
    assert source.merged_into_id == suite.p.pk and grant.revoked_at
    assert event.manifest["moved"]["encounters.encounter.patient"] == [encounter.pk]
    assert encounter.history.first().patient_id == source.pk


def test_merge_refuses_two_active_admissions(suite):
    other = Patient.objects.create(
        first_name="Duplicate", last_name="Patient", gender="F", facility=suite.f
    )
    for name, patient in [("1", suite.p), ("2", other)]:
        Admission.objects.create(
            patient=patient,
            bed=Bed.objects.create(facility=suite.f, ward="General", name=name),
            reason="Observation",
            created_by=suite.u,
        )
    review = DuplicateReview.objects.create(
        patient=suite.p,
        candidate=other,
        reason="Identity verified",
        status="confirmed",
        created_by=suite.u,
    )
    with pytest.raises(ValidationError):
        merge_patients(review.pk, suite.u, "Verified")
    assert not PatientMerge.objects.exists()


def setup_coverage(suite):
    invoice = Invoice.objects.create(patient=suite.p, total_amount=100)
    InvoiceLine.objects.create(
        invoice=invoice,
        code="CONSULT",
        quantity=1,
        unit_price=100,
        source_ref="consult:1",
    )
    payer = Payer.objects.create(name="Test payer", facility=suite.f)
    day = timezone.localdate()
    CoveragePlan.objects.create(
        payer=payer,
        name="Contract",
        service_code="CONSULT",
        covered_percent=80,
        valid_from=day,
        valid_until=day + timedelta(days=365),
    )
    policy = Policy.objects.create(
        patient=suite.p,
        payer=payer,
        membership_number="MEM001",
        valid_from=day,
        valid_until=day + timedelta(days=365),
        verified_at=timezone.now(),
        verification_reference="Payer confirmed",
        created_by=suite.u,
    )
    return invoice, policy


def test_insurance_copay_and_remittance(suite):
    invoice, policy = setup_coverage(suite)
    claim = prepare_claim(invoice.pk, policy.pk, "", suite.u)
    assert claim.amount == 80 and claim.allocations.get().patient_amount == 20
    claim.status = "accepted"
    claim.save()
    remittance = Remittance.objects.create(
        claim=claim, amount=80, reference="BANK001", created_by=suite.u
    )
    post_remittance(remittance)
    post_remittance(remittance)
    invoice.refresh_from_db()
    assert invoice.paid_amount == 80
    assert Payment.objects.get().method == "insurance"
    assert (
        suite.client.get(reverse("suite-claim-export", args=[claim.pk])).status_code
        == 200
    )


def test_overlapping_insurance_rules_rejected(suite):
    invoice, policy = setup_coverage(suite)
    rule = CoveragePlan.objects.get()
    rule.pk = None
    rule.save()
    with pytest.raises(ValidationError):
        prepare_claim(invoice.pk, policy.pk, "", suite.u)
    assert not Claim.objects.exists()


def test_mobile_money_requires_verified_matching_result_and_is_idempotent(suite):
    invoice = Invoice.objects.create(patient=suite.p, total_amount=100)
    intent = PaymentIntent.objects.create(
        invoice=invoice, amount=100, phone="+256700000000", created_by=suite.u
    )
    provider = Mock(environment="mtnuganda")
    provider.status.return_value = {
        "status": "SUCCESSFUL",
        "amount": "100",
        "currency": "UGX",
        "externalId": str(intent.reference),
        "financialTransactionId": "TX1",
    }
    submit_collection(intent.pk, provider)
    submit_collection(intent.pk, provider)
    assert provider.request.call_count == 1
    reconcile_collection(intent.pk, provider)
    reconcile_collection(intent.pk, provider)
    assert Payment.objects.count() == 1
    invoice.refresh_from_db()
    assert invoice.paid_amount == 100


def test_sandbox_or_mismatch_never_posts_payment(suite):
    invoice = Invoice.objects.create(patient=suite.p, total_amount=100)
    intent = PaymentIntent.objects.create(
        invoice=invoice, amount=100, phone="+256700000000", created_by=suite.u
    )
    provider = Mock(environment="sandbox")
    provider.status.return_value = {
        "status": "SUCCESSFUL",
        "amount": "100",
        "currency": "UGX",
        "externalId": str(intent.reference),
    }
    reconcile_collection(intent.pk, provider)
    assert not Payment.objects.exists()
    provider.environment = "mtnuganda"
    provider.status.return_value["amount"] = "10"
    reconcile_collection(intent.pk, provider)
    assert not Payment.objects.exists()


def test_lab_catalog_rejects_unreceived_or_wrong_specimen(suite):
    order = Order.objects.create(
        patient=suite.p, order_type="lab", code="LAB", billable=False
    )
    panel = LabPanel.objects.create(
        facility=suite.f, name="Test", code="TEST", specimen_type="Blood"
    )
    analyte = LabAnalyte.objects.create(
        panel=panel,
        code="X",
        name="Analyte",
        units="unit",
        low=1,
        high=10,
        reference_note="Test fixture only",
    )
    specimen = Specimen.objects.create(
        order=order, specimen_type="Blood", created_by=suite.u
    )
    result = OrderResult(
        order=order, specimen=specimen, catalog_analyte=analyte, value="4"
    )
    with pytest.raises(ValidationError):
        validate_new_record(result, suite.u)
    specimen.status = "received"
    specimen.save()
    validate_new_record(result, suite.u)
    assert result.analyte == "Analyte" and result.units == "unit"


def test_card_and_barcode_render(suite):
    assert suite.client.get(reverse("suite-card", args=[suite.p.pk])).status_code == 200
    response = suite.client.get(reverse("suite-barcode", args=["patient", suite.p.pk]))
    assert response.status_code == 200 and b"<svg" in response.content


def test_admin_scope_and_login_throttle(suite):
    assert suite.client.get("/admin/").status_code == 403
    suite.client.logout()
    for _ in range(10):
        suite.client.post(
            "/accounts/login/", {"username": "bad-user", "password": "bad-password"}
        )
    response = suite.client.post(
        "/accounts/login/", {"username": "bad-user", "password": "bad-password"}
    )
    assert response.status_code == 429 and "Retry-After" in response


def test_sms_webhook_auth_and_terminal_state(suite, monkeypatch):
    monkeypatch.setenv("SMS_CALLBACK_TOKEN", "x" * 40)
    SmsDelivery.objects.create(
        key="reminder:1",
        payload_hash="a" * 64,
        status="accepted",
        provider_reference="AT1",
    )
    assert (
        suite.client.post(
            "/integrations/sms/delivery/", {"id": "AT1", "status": "Success"}
        ).status_code
        == 403
    )
    url = "/integrations/sms/delivery/?token=" + "x" * 40
    assert suite.client.post(url, {"id": "AT1", "status": "Success"}).status_code == 200
    suite.client.post(url, {"id": "AT1", "status": "Failed"})
    assert SmsDelivery.objects.get().status == "delivered"


def test_sms_adapter_does_not_repeat_ambiguous_requests(suite, monkeypatch):
    from apps.integrations.providers import AfricasTalkingSMS

    monkeypatch.setenv("AT_USERNAME", "test")
    monkeypatch.setenv("AT_API_KEY", "test-only")
    send = Mock(side_effect=TimeoutError)
    monkeypatch.setattr("apps.integrations.providers.http", send)
    backend = AfricasTalkingSMS()
    with pytest.raises(TimeoutError):
        backend.send("+256700000000", "Reminder", idempotency_key="reminder:2")
    with pytest.raises(ValueError):
        backend.send("+256700000000", "Reminder", idempotency_key="reminder:2")
    assert send.call_count == 1
