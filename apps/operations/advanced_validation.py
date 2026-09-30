import re
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import (
    LabAnalyte,
    InpatientOrder,
    CarePlan,
    SupplierCredit,
    CoveragePlan,
    Policy,
    Remittance,
    PaymentIntent,
    Claim,
)
from apps.orders.models import OrderResult


def validate_new_record(obj, actor):
    if (
        isinstance(obj, LabAnalyte)
        and obj.low is not None
        and obj.high is not None
        and obj.low > obj.high
    ):
        raise ValidationError("Lower reference limit exceeds upper limit.")
    if isinstance(obj, (InpatientOrder, CarePlan)) and obj.admission.discharged_at:
        raise ValidationError("Admission is already discharged.")
    if isinstance(obj, InpatientOrder):
        if obj.admission.patient_id != obj.prescription_item.prescription.patient_id:
            raise ValidationError("Prescription must belong to the admitted patient.")
        if not 1 <= obj.interval_hours <= 168 or obj.ends_at <= obj.starts_at:
            raise ValidationError("Enter a valid schedule and interval (1–168 hours).")
    if isinstance(obj, (CoveragePlan, Policy)) and obj.valid_until < obj.valid_from:
        raise ValidationError("Validity dates are reversed.")
    if isinstance(obj, Policy) and obj.patient.facility_id != obj.payer.facility_id:
        raise ValidationError("Payer and patient must share a facility.")
    if isinstance(obj, SupplierCredit):
        if obj.amount <= 0:
            raise ValidationError("Credit amount must be positive.")
        if obj.applied_po_id and (
            obj.applied_po.supplier_id != obj.supplier_id
            or obj.applied_po.facility_id != obj.facility_id
        ):
            raise ValidationError(
                "Credit and purchase order must share supplier and facility."
            )
    if isinstance(obj, Remittance) and obj.amount <= 0:
        raise ValidationError("Remittance must be positive.")
    if isinstance(obj, Claim):
        from django.db.models import Sum
        from apps.billing.models import Invoice

        Invoice.objects.select_for_update().get(pk=obj.invoice_id)
        reserved = Claim.objects.filter(invoice_id=obj.invoice_id).exclude(
            status="rejected"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if reserved + obj.amount > obj.invoice.total_amount:
            raise ValidationError("Claims exceed the invoice total.")
    if isinstance(obj, PaymentIntent):
        if (
            obj.amount <= 0
            or obj.amount > obj.invoice.total_amount - obj.invoice.paid_amount
        ):
            raise ValidationError("Collection amount exceeds outstanding balance.")
        if not re.fullmatch(r"\+?[1-9][0-9]{7,14}", obj.phone):
            raise ValidationError(
                "Use the phone country code and digits, for example +256…"
            )
    if isinstance(obj, OrderResult):
        if obj.specimen_id and (
            obj.specimen.order_id != obj.order_id or obj.specimen.status != "received"
        ):
            raise ValidationError("Select a received specimen for this order.")
        if obj.catalog_analyte_id:
            analyte = obj.catalog_analyte
            if analyte.panel.facility_id != obj.order.patient.facility_id:
                raise ValidationError("Analyte belongs to another facility.")
            if not obj.specimen_id:
                raise ValidationError("A catalog result requires a received specimen.")
            if (
                obj.specimen.specimen_type.casefold()
                != analyte.panel.specimen_type.casefold()
            ):
                raise ValidationError("Specimen type does not match the panel.")
            obj.analyte = analyte.name
            obj.units = analyte.units
            obj.reference_range = f'{analyte.low if analyte.low is not None else ""} – {analyte.high if analyte.high is not None else ""} {analyte.reference_note}'.strip()
            if analyte.low is not None or analyte.high is not None:
                try:
                    numeric = Decimal(obj.value)
                except Exception:
                    raise ValidationError("This analyte requires a numeric value.")
                if not numeric.is_finite():
                    raise ValidationError("Numeric value must be finite.")
