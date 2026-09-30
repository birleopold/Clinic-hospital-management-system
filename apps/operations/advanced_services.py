"""Transactional workflows shared by staff views and management commands."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.apps import apps
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from apps.demographics.models import Patient
from apps.billing.models import Invoice, Payment
from .models import (
    PatientMerge,
    DuplicateReview,
    Admission,
    PortalGrant,
    Claim,
    CoveragePlan,
    Policy,
    ClaimAllocation,
    Remittance,
)


@transaction.atomic
def merge_patients(review_id, actor, reason):
    review = DuplicateReview.objects.select_for_update().get(pk=review_id)
    if not (actor.is_superuser or actor.role in ("admin", "manager")):
        raise PermissionDenied
    if review.status != "confirmed" or not reason.strip():
        raise ValidationError("Confirm identity and enter a merge reason first.")
    from common.facility_scope import filter_by_facility

    if (
        filter_by_facility(
            Patient.objects.filter(pk__in=[review.patient_id, review.candidate_id]),
            actor,
        ).count()
        != 2
    ):
        raise PermissionDenied
    if PatientMerge.objects.filter(review=review).exists():
        return PatientMerge.objects.get(review=review)
    patients = {
        p.pk: p
        for p in Patient.objects.select_for_update()
        .filter(pk__in=[review.patient_id, review.candidate_id])
        .order_by("pk")
    }
    target, source = patients[review.patient_id], patients[review.candidate_id]
    if source.pk == target.pk or source.merged_into_id or target.merged_into_id:
        raise ValidationError("Choose two active canonical records.")
    if source.facility_id != target.facility_id:
        raise ValidationError("Cross-facility merges are not allowed.")
    if (
        Admission.objects.filter(
            patient__in=[source, target], discharged_at__isnull=True
        ).count()
        > 1
    ):
        raise ValidationError("Resolve the two active admissions before merging.")
    # Preserve identity provenance and immutable history. Do not overwrite target demographics.
    manifest = {
        "source_identifier": str(source.medical_record_id),
        "target_identifier": str(target.medical_record_id),
        "moved": {},
    }
    excluded = {
        "demographics.patient",
        "operations.duplicatereview",
        "operations.patientmerge",
        "operations.portalgrant",
    }
    for model in apps.get_models():
        if model._meta.label_lower in excluded or model.__name__.startswith(
            "Historical"
        ):
            continue
        for field in model._meta.fields:
            if field.is_relation and field.related_model is Patient:
                qs = model.objects.filter(**{field.attname: source.pk})
                ids = list(qs.values_list("pk", flat=True))
                if ids:
                    # Explicit manifest records every relink. Monetary entries and original history remain intact.
                    manifest["moved"][f"{model._meta.label_lower}.{field.name}"] = ids
                    qs.update(**{field.attname: target.pk})
    PortalGrant.objects.filter(
        patient__in=[source, target], revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    source.merged_into = target
    source.save(update_fields=["merged_into"])
    if source.allergy_status == "recorded" and target.allergy_status != "recorded":
        target.allergy_status = "recorded"
        target.save(update_fields=["allergy_status"])
    return PatientMerge.objects.create(
        source=source,
        target=target,
        review=review,
        reason=reason,
        manifest=manifest,
        created_by=actor,
    )


@transaction.atomic
def prepare_claim(invoice_id, policy_id, authorization, actor):
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    policy = Policy.objects.select_for_update().get(pk=policy_id)
    today = timezone.localdate()
    if (
        policy.patient_id != invoice.patient_id
        or not policy.verified_at
        or not policy.valid_from <= today <= policy.valid_until
    ):
        raise ValidationError(
            "An active, verified policy for this patient is required."
        )
    if policy.payer.facility_id != invoice.patient.facility_id:
        raise ValidationError("Policy payer and patient facilities do not match.")
    if (
        invoice.status == Invoice.CANCELLED
        or invoice.paid_amount
        or invoice.lines.filter(line_total__lt=0).exists()
    ):
        raise ValidationError(
            "Prepare coverage before payments or credit adjustments; reconcile adjusted invoices manually."
        )
    if Claim.objects.filter(invoice=invoice).exists():
        raise ValidationError(
            "This invoice already has a claim. Update or reconcile that claim."
        )
    rules = CoveragePlan.objects.filter(
        payer=policy.payer, valid_from__lte=today, valid_until__gte=today
    )
    allocations = []
    for line in invoice.lines.all():
        candidates = list(rules.filter(service_code=line.code)) or list(
            rules.filter(service_code="*")
        )
        if len(candidates) > 1:
            raise ValidationError(f"Overlapping coverage rules for {line.code}.")
        rule = candidates[0] if candidates else None
        if rule and rule.requires_authorization and not authorization.strip():
            raise ValidationError(f"Authorization is required for {line.code}.")
        covered = (
            line.line_total * (rule.covered_percent if rule else 0) / Decimal("100")
        ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        allocations.append(
            (
                line,
                covered,
                {
                    "rule": rule.pk if rule else None,
                    "percent": str(rule.covered_percent if rule else 0),
                    "service_code": line.code,
                },
            )
        )
    amount = sum((a[1] for a in allocations), Decimal("0"))
    if amount <= 0:
        raise ValidationError("No covered services on this invoice.")
    claim = Claim.objects.create(
        invoice=invoice,
        payer=policy.payer,
        membership_number=policy.membership_number,
        authorization_reference=authorization,
        amount=amount,
        created_by=actor,
    )
    for line, covered, snapshot in allocations:
        ClaimAllocation.objects.create(
            claim=claim,
            line=line,
            payer_amount=covered,
            patient_amount=line.line_total - covered,
            rule_snapshot=snapshot,
        )
    return claim


@transaction.atomic
def post_remittance(remittance):
    remittance = Remittance.objects.select_for_update().get(pk=remittance.pk)
    if remittance.payment_id:
        return remittance
    claim = Claim.objects.select_for_update().get(pk=remittance.claim_id)
    invoice = Invoice.objects.select_for_update().get(pk=claim.invoice_id)
    if claim.status != "accepted":
        raise ValidationError("Record payer acceptance first.")
    prior = claim.remittances.exclude(pk=remittance.pk).filter(
        payment__isnull=False
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    if (
        invoice.status == Invoice.CANCELLED
        or remittance.amount <= 0
        or prior + remittance.amount > claim.amount
        or remittance.amount > invoice.total_amount - invoice.paid_amount
    ):
        raise ValidationError("Remittance exceeds the claim or invoice balance.")
    payment = Payment.objects.create(
        invoice=invoice,
        amount=remittance.amount,
        method="insurance",
        notes=f"Remittance {remittance.reference}",
    )
    invoice.paid_amount += remittance.amount
    invoice.status = (
        Invoice.PAID if invoice.paid_amount >= invoice.total_amount else Invoice.READY
    )
    invoice.save(update_fields=["paid_amount", "status"])
    remittance.payment = payment
    remittance.save(update_fields=["payment"])
    return remittance


def scheduled_doses(order, until=None):
    end = min(order.ends_at, until or timezone.now() + timedelta(days=1))
    if order.stopped_at:
        end = min(end, order.stopped_at)
    if order.admission.discharged_at:
        end = min(end, order.admission.discharged_at)
    if not 1 <= order.interval_hours <= 168 or order.ends_at <= order.starts_at:
        raise ValidationError("A positive schedule interval and end date are required.")
    cursor = order.starts_at
    doses = []
    # Worklist bounded to the last day and next day; avoid unbounded old schedules.
    floor = timezone.now() - timedelta(days=1)
    if cursor < floor:
        steps = max(
            0, int((floor - cursor).total_seconds() // (order.interval_hours * 3600))
        )
        cursor += timedelta(hours=steps * order.interval_hours)
    while cursor <= end and len(doses) < 100:
        doses.append(cursor)
        cursor += timedelta(hours=order.interval_hours)
    return doses
