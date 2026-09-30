from io import BytesIO
from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
    ImproperlyConfigured,
)
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Sum, Q
from common.exports import csv_response
from common.facility_scope import filter_by_facility
from .views import allowed, scoped
from .models import (
    Policy,
    Claim,
    PaymentIntent,
    InpatientOrder,
    PackageUnit,
    StockLocation,
)
from .advanced_services import prepare_claim, scheduled_doses
from apps.demographics.models import Patient
from apps.billing.models import Invoice
from apps.inventory.models import InventoryItem, Batch


@login_required
def identity_card(request, pk):
    if not allowed(request.user, ["reception", "clinician", "nurse"]):
        raise PermissionDenied
    patient = get_object_or_404(
        filter_by_facility(Patient.objects.all(), request.user), pk=pk
    )
    if patient.merged_into_id:
        return redirect("suite-card", pk=patient.merged_into_id)
    return render(request, "operations/identity_card.html", {"patient": patient})


@login_required
def barcode(request, kind, pk):
    import qrcode
    import qrcode.image.svg

    if kind == "patient":
        if not allowed(request.user, ["reception", "clinician", "nurse"]):
            raise PermissionDenied
        obj = get_object_or_404(
            filter_by_facility(Patient.objects.all(), request.user), pk=pk
        )
        value = str(obj.medical_record_id)
    elif kind == "specimen":
        from .models import Specimen

        if not allowed(request.user, ["lab", "clinician", "nurse"]):
            raise PermissionDenied
        obj = get_object_or_404(
            scoped(Specimen, request.user, "order__patient__facility_id"), pk=pk
        )
        value = str(obj.accession)
    else:
        raise PermissionDenied
    svg = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage).to_string()
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def prepare_insurance(request):
    if not allowed(request.user, ["cashier", "manager"]):
        raise PermissionDenied

    class CoverageForm(forms.Form):
        invoice = forms.ModelChoiceField(
            queryset=scoped(Invoice, request.user, "patient__facility_id")
        )
        policy = forms.ModelChoiceField(
            queryset=scoped(Policy, request.user, "patient__facility_id").filter(
                verified_at__isnull=False
            )
        )
        authorization = forms.CharField(max_length=100, required=False)

    form = CoverageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            claim = prepare_claim(
                form.cleaned_data["invoice"].pk,
                form.cleaned_data["policy"].pk,
                form.cleaned_data["authorization"],
                request.user,
            )
            messages.success(
                request,
                f"Claim #{claim.pk} prepared with saved coverage and co-pay allocations.",
            )
            return redirect("suite-collection", slug="claims")
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
    return render(
        request,
        "operations/task_form.html",
        {
            "title": "Calculate insurance coverage",
            "form": form,
            "button": "Prepare claim",
        },
    )


@login_required
def claim_export(request, pk):
    if not allowed(request.user, ["cashier", "manager"]):
        raise PermissionDenied
    claim = get_object_or_404(
        scoped(Claim, request.user, "invoice__patient__facility_id"), pk=pk
    )
    rows = [
        [
            claim.pk,
            claim.membership_number,
            a.line.code,
            a.line.quantity,
            a.line.line_total,
            a.payer_amount,
            a.patient_amount,
            claim.authorization_reference,
        ]
        for a in claim.allocations.select_related("line")
    ]
    headers = [
        "claim",
        "member",
        "service",
        "quantity",
        "charge",
        "payer_amount",
        "patient_copay",
        "authorization",
    ]
    return csv_response(
        f"claim-{claim.pk}.csv", headers, [dict(zip(headers, row)) for row in rows]
    )


@login_required
@require_POST
def collection_provider(request, pk, operation):
    if not allowed(request.user, ["cashier", "manager"]):
        raise PermissionDenied
    intent = get_object_or_404(
        scoped(PaymentIntent, request.user, "invoice__patient__facility_id"), pk=pk
    )
    from apps.integrations.collections import submit_collection, reconcile_collection

    try:
        if operation == "request":
            submit_collection(intent.pk)
        elif operation == "reconcile":
            reconcile_collection(intent.pk)
        else:
            raise PermissionDenied
        messages.success(
            request, "Provider operation completed. Review the collection state."
        )
    except ImproperlyConfigured as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except Exception:
        messages.error(
            request, "Provider unavailable. Reconcile this reference before retrying."
        )
    return redirect("suite-collection", slug="collections")


@login_required
def medication_round(request):
    if not allowed(request.user, ["nurse", "clinician"]):
        raise PermissionDenied
    from .models import MedicationAdministration

    rows = []
    for order in (
        scoped(InpatientOrder, request.user, "admission__patient__facility_id")
        .filter(stopped_at__isnull=True, admission__discharged_at__isnull=True)
        .select_related("admission__patient", "prescription_item")[:200]
    ):
        outcomes = {
            a.scheduled_for: a
            for a in MedicationAdministration.objects.filter(
                admission=order.admission, prescription_item=order.prescription_item
            )
        }
        for due in scheduled_doses(order):
            rows.append({"order": order, "due": due, "outcome": outcomes.get(due)})
    rows.sort(key=lambda row: row["due"])
    return render(request, "operations/rounds.html", {"rows": rows})


@login_required
def reorder_report(request):
    if not allowed(request.user, ["store", "manager", "pharmacy"]):
        raise PermissionDenied
    from apps.pharmacy.services import usable_batches

    balances = (
        filter_by_facility(
            usable_batches(), request.user, field="location__facility_id"
        )
        .values("item_id")
        .annotate(total=Sum("quantity_on_hand"))
    )
    totals = {r["item_id"]: r["total"] for r in balances}
    rows = [
        {
            "item": i,
            "balance": totals.get(i.pk, 0),
            "suggested": i.reorder_level - totals.get(i.pk, 0),
        }
        for i in InventoryItem.objects.filter(reorder_level__gt=0)
        if totals.get(i.pk, 0) < i.reorder_level
    ]
    return render(request, "operations/reorder.html", {"rows": rows})


@login_required
def specialty_follow_up(request):
    """Operational due dates entered by staff; not generated clinical schedules."""
    if not allowed(request.user, ["clinician", "nurse"]):
        raise PermissionDenied
    from datetime import timedelta
    from django.db.models import OuterRef, Subquery
    from .models import (
        TheatreCase,
        Pregnancy,
        MaternityVisit,
        Vaccination,
        RehabilitationPlan,
        RehabilitationSession,
    )

    today = timezone.localdate()
    next_week = timezone.now() + timedelta(days=7)
    latest_maternity = MaternityVisit.objects.filter(
        pregnancy_id=OuterRef("pk"), amendment__isnull=True
    ).order_by("-occurred_at", "-pk")
    latest_rehab = RehabilitationSession.objects.filter(
        plan_id=OuterRef("pk"), amendment__isnull=True
    ).order_by("-occurred_at", "-pk")
    vaccinations = (
        scoped(Vaccination, request.user, "patient__facility_id")
        .filter(status__in=["scheduled", "deferred"], due_on__lte=today)
        .select_related("patient")
        .order_by("due_on")
    )
    maternity = (
        scoped(Pregnancy, request.user, "patient__facility_id")
        .annotate(next_follow_up=Subquery(latest_maternity.values("follow_up_on")[:1]))
        .filter(next_follow_up__lte=today)
        .select_related("patient")
        .order_by("next_follow_up")
    )
    rehab = (
        scoped(RehabilitationPlan, request.user, "patient__facility_id")
        .filter(status="active")
        .annotate(next_session=Subquery(latest_rehab.values("next_visit_on")[:1]))
        .filter(Q(review_on__lte=today) | Q(next_session__lte=today))
        .select_related("patient")
        .order_by("review_on")
    )
    theatre = (
        scoped(TheatreCase, request.user, "patient__facility_id")
        .exclude(status__in=["completed", "cancelled"])
        .filter(starts_at__lte=next_week)
        .select_related("patient", "room", "surgeon")
        .order_by("starts_at")
    )
    groups = []
    for label, slug, queryset, date_field in [
        ("Vaccinations due", "vaccinations", vaccinations, "due_on"),
        ("Maternity follow-up", "maternity-visits", maternity, "next_follow_up"),
        ("Rehabilitation reviews / sessions", "rehabilitation", rehab, "review_on"),
        ("Theatre: overdue and next seven days", "theatre", theatre, "starts_at"),
    ]:
        groups.append(
            {
                "label": label,
                "slug": slug,
                "count": queryset.count(),
                "rows": [
                    {
                        "record": r,
                        "patient": r.patient,
                        "due": getattr(r, date_field),
                        "session_due": getattr(r, "next_session", None),
                    }
                    for r in queryset[:100]
                ],
            }
        )
    return render(
        request,
        "operations/specialty_follow_up.html",
        {"groups": groups, "today": today},
    )


@login_required
def specialty_detail(request, slug, pk):
    from .views import config, display_value
    from .specialty_services import SPECIALTIES
    from django.http import Http404

    model, title, fields, scope, roles = config(request, slug)
    if model not in SPECIALTIES:
        raise Http404
    record = get_object_or_404(scoped(model, request.user, scope), pk=pk)
    details = []
    for field in model._meta.fields:
        if field.name == "id":
            continue
        value = getattr(record, field.name)
        if field.choices:
            value = getattr(record, "get_" + field.name + "_display")()
        details.append({"label": field.verbose_name, "value": display_value(value)})
    return render(
        request,
        "operations/specialty_detail.html",
        {
            "record": record,
            "slug": slug,
            "title": title,
            "details": details,
            "history": record.history.select_related("history_user").order_by(
                "-history_date"
            ),
        },
    )
