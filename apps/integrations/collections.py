from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from apps.billing.models import Invoice, Payment
from apps.operations.models import PaymentIntent
from .providers import MTNCollection


def submit_collection(pk, provider=None):
    provider = provider or MTNCollection()
    with transaction.atomic():
        intent = PaymentIntent.objects.select_for_update().get(pk=pk)
        if intent.status != "pending":
            return intent
        invoice = Invoice.objects.select_for_update().get(pk=intent.invoice_id)
        if (
            intent.amount <= 0
            or intent.amount > invoice.total_amount - invoice.paid_amount
            or invoice.status == Invoice.CANCELLED
        ):
            raise ValidationError("Collection exceeds the outstanding invoice balance.")
        reserved = PaymentIntent.objects.filter(
            invoice=invoice, status__in=["requested", "review"], payment__isnull=True
        ).exclude(pk=intent.pk).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if intent.amount + reserved > invoice.total_amount - invoice.paid_amount:
            raise ValidationError(
                "Another unresolved collection already reserves this invoice balance."
            )
        # Commit the stable reference before network I/O. Never blindly retry an uncertain POST.
        intent.status = "requested"
        intent.save(update_fields=["status"])
    try:
        provider.request(intent)
    except Exception:
        PaymentIntent.objects.filter(pk=pk).update(
            last_error="Request outcome uncertain. Reconcile using the existing reference before retrying."
        )
    return PaymentIntent.objects.get(pk=pk)


def reconcile_collection(pk, provider=None):
    provider = provider or MTNCollection()
    intent = PaymentIntent.objects.get(pk=pk)
    result = provider.status(
        intent
    )  # Authenticated server-to-server verification; never trust a webhook amount.
    with transaction.atomic():
        intent = PaymentIntent.objects.select_for_update().get(pk=pk)
        if intent.payment_id:
            return intent
        status = result.get("status")
        if status == "FAILED":
            intent.status = "failed"
            intent.save(update_fields=["status"])
            return intent
        if status != "SUCCESSFUL":
            return intent
        invoice = Invoice.objects.select_for_update().get(pk=intent.invoice_id)
        try:
            matches = (
                Decimal(str(result.get("amount"))) == intent.amount
                and result.get("currency") == intent.currency
                and result.get("externalId") == str(intent.reference)
            )
        except Exception:
            matches = False
        if (
            not matches
            or intent.amount > invoice.total_amount - invoice.paid_amount
            or invoice.status == Invoice.CANCELLED
        ):
            intent.status = "review"
            intent.last_error = (
                "Provider result or invoice balance requires reconciliation."
            )
            intent.save()
            return intent
        # Sandbox outcomes never create real ledger payments.
        if getattr(provider, "environment", None) == "sandbox":
            intent.status = "review"
            intent.last_error = "Sandbox transaction verified; no real payment posted."
            intent.save()
            return intent
        payment = Payment.objects.create(
            invoice=invoice,
            amount=intent.amount,
            method="mobile_money",
            notes=f"MTN {intent.reference}",
        )
        invoice.paid_amount += intent.amount
        invoice.status = (
            Invoice.PAID
            if invoice.paid_amount >= invoice.total_amount
            else Invoice.READY
        )
        invoice.save(update_fields=["paid_amount", "status"])
        intent.payment = payment
        intent.status = "successful"
        intent.provider_reference = str(result.get("financialTransactionId", ""))[:160]
        intent.last_error = ""
        intent.save()
        return intent
