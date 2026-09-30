"""Encrypted browser drafts use the same validated write services as connected staff."""

from datetime import timedelta
import copy
import hashlib
import json
import uuid
from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.http import JsonResponse, QueryDict, FileResponse
from django.utils.datastructures import MultiValueDict
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from common.facility_scope import user_staff_facility_id
from apps.demographics.models import Patient
from .models import OfflineDevice, OfflineReceipt
from .views import MODULES, RELATIONS, allowed, collection_form, save_collection_form

# Append-only documentation only. Clinical release, financial and stock mutations
# continue to require their connected, row-locked review workflows.
OFFLINE_MODULES = (
    "clinical",
    "referrals",
    "observations",
    "maternity-visits",
    "labour-observations",
    "perioperative",
    "rehab-sessions",
    "rehab-outcomes",
    "vaccine-adverse-events",
)
SALT = "clinic-offline-v1"
MAX_AGE = 7 * 24 * 60 * 60


def actor(request):
    user = request.user
    if not user.is_authenticated or not allowed(user, ("clinician", "nurse")):
        raise PermissionDenied("Sign in as clinical staff to use offline drafts.")
    facility = user_staff_facility_id(user)
    if not facility:
        raise PermissionDenied("An assigned facility is required for offline access.")
    return user, facility


def json_body(request):
    try:
        if len(request.body) > 250000:
            raise ValueError
        result = json.loads(request.body)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Invalid or oversized request.")


def response(data, status=200):
    result = JsonResponse(data, status=status)
    result["Cache-Control"] = "private, no-store"
    return result


def digest(obj):
    data = {
        field.attname: getattr(obj, field.attname)
        for field in obj._meta.concrete_fields
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


def restrict(form, patient_ids, facility_id):
    for field in form.fields.values():
        if isinstance(field, forms.ModelChoiceField):
            related = field.queryset.model
            path = RELATIONS.get(related, "")
            if related is Patient:
                field.queryset = field.queryset.filter(
                    pk__in=patient_ids, facility_id=facility_id
                )
            elif "patient__" in path:
                field.queryset = field.queryset.filter(
                    **{
                        path.rsplit("facility_id", 1)[0] + "pk__in": patient_ids,
                        path: facility_id,
                    }
                )
            else:
                field.queryset = field.queryset.none()
    return form


def referenced_patient(obj):
    if isinstance(obj, Patient):
        return obj
    path = RELATIONS.get(type(obj), "")
    if "patient__" not in path:
        return None
    current = obj
    for part in path.rsplit("__facility_id", 1)[0].split("__"):
        current = getattr(current, part)
    return current


def device_for(request, device_id, lock=False):
    user, facility = actor(request)
    qs = (
        OfflineDevice.objects.select_for_update()
        if lock
        else OfflineDevice.objects.all()
    )
    try:
        return qs.get(
            pk=uuid.UUID(str(device_id)),
            owner=user,
            facility_id=facility,
            revoked_at__isnull=True,
        )
    except (ValueError, OfflineDevice.DoesNotExist):
        raise PermissionDenied(
            "Device is revoked, unavailable, or belongs to a different account/facility."
        )


def shell(request):
    # Deliberately no patient/user data or CSRF token in this cacheable app shell.
    result = render(request, "operations/offline.html")
    result["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return result


@require_GET
def service_worker(request):
    result = FileResponse(
        (settings.BASE_DIR / "static/js/offline-sw.js").open("rb"),
        content_type="text/javascript",
    )
    result["Service-Worker-Allowed"] = "/offline/"
    result["Cache-Control"] = "no-cache"
    return result


@require_GET
def session(request):
    if not request.user.is_authenticated:
        return response({"error": "Sign in online first."}, 401)
    user, facility = actor(request)
    return response(
        {
            "user_id": user.pk,
            "username": user.get_username(),
            "facility_id": facility,
            "csrf": get_token(request),
            "can_manage_devices": user.is_superuser or user.role == "admin",
        }
    )


@require_GET
def patients(request):
    user, facility = actor(request)
    query = request.GET.get("q", "").strip()[:100]
    if len(query) < 2:
        return response({"patients": []})
    filters = Q(first_name__icontains=query) | Q(last_name__icontains=query)
    try:
        filters |= Q(medical_record_id=uuid.UUID(query))
    except ValueError:
        pass
    records = Patient.objects.filter(
        filters, facility_id=facility, merged_into__isnull=True
    ).order_by("last_name", "first_name")[:20]
    return response(
        {
            "patients": [
                {"id": p.pk, "label": f"{p} · {p.medical_record_id}"} for p in records
            ]
        }
    )


def devices(request):
    user, facility = actor(request)
    if request.method == "GET":
        records = OfflineDevice.objects.filter(facility_id=facility)
        if request.GET.get("facility") != "1" or not (
            user.is_superuser or user.role == "admin"
        ):
            records = records.filter(owner=user)
        return response(
            {
                "devices": list(
                    records.values(
                        "id", "label", "owner__username", "created_at", "revoked_at"
                    )
                )
            }
        )
    if request.method != "POST":
        return response({"error": "Method not allowed."}, 405)
    try:
        data = json_body(request)
        if data.get("revoke"):
            if user.is_superuser or user.role == "admin":
                try:
                    device = OfflineDevice.objects.get(
                        pk=uuid.UUID(str(data["revoke"])), facility_id=facility
                    )
                except (ValueError, OfflineDevice.DoesNotExist):
                    raise PermissionDenied
            else:
                device = device_for(request, data["revoke"])
            device.revoked_at = timezone.now()
            device._history_user = user
            device.save()
            return response({"revoked": str(device.pk)})
        label = str(data.get("label", "")).strip()[:80]
        if not label:
            raise ValidationError("Name this device.")
        if (
            OfflineDevice.objects.filter(owner=user, revoked_at__isnull=True).count()
            >= 10
        ):
            raise ValidationError(
                "Revoke an unused device before enrolling another (maximum ten)."
            )
        device = OfflineDevice(owner=user, facility_id=facility, label=label)
        device._history_user = user
        device.save()
        return response({"device_id": str(device.pk)}, 201)
    except ValidationError as exc:
        return response({"error": "; ".join(exc.messages)}, 400)


@require_POST
def prepare(request):
    try:
        data = json_body(request)
        device = device_for(request, data.get("device_id"))
        ids = data.get("patient_ids", [])
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 20
            or any(type(x) is not int for x in ids)
        ):
            raise ValidationError("Select between one and twenty patients.")
        ids = sorted(set(ids))
        patients = list(
            Patient.objects.filter(
                pk__in=ids, facility_id=device.facility_id, merged_into__isnull=True
            )
        )
        if len(patients) != len(ids):
            raise PermissionDenied
        grant = signing.dumps(
            {"device": str(device.pk), "user": request.user.pk, "patients": ids},
            salt=SALT,
        )
        schemas = []
        blank = copy.copy(request)
        blank.method = "GET"
        blank.POST = QueryDict("")
        blank._files = MultiValueDict()
        for slug in OFFLINE_MODULES:
            model, title, names, scope, roles = MODULES[slug]
            if not allowed(request.user, roles):
                continue
            form = restrict(
                collection_form(blank, model, names), ids, device.facility_id
            )
            fields = []
            for name, field in form.fields.items():
                entry = {
                    "name": name,
                    "label": field.label or name.replace("_", " ").capitalize(),
                    "required": field.required,
                    "help": str(field.help_text),
                    "max_length": getattr(field, "max_length", None),
                }
                if isinstance(field, forms.ModelChoiceField):
                    count = field.queryset.count()
                    choices = []
                    for obj in field.queryset.order_by("-pk")[:200]:
                        parent = referenced_patient(obj)
                        token = signing.dumps(
                            {
                                "device": str(device.pk),
                                "field": name,
                                "slug": slug,
                                "model": obj._meta.label_lower,
                                "pk": obj.pk,
                                "digest": digest(obj),
                                "patient_pk": parent.pk if parent else None,
                                "patient_digest": digest(parent) if parent else None,
                            },
                            salt=SALT,
                        )
                        choices.append(
                            {
                                "value": str(obj.pk),
                                "label": field.label_from_instance(obj)
                                + (
                                    f" · {parent} · {str(parent.medical_record_id)[:8]}"
                                    if parent and not isinstance(obj, Patient)
                                    else ""
                                ),
                                "proof": token,
                            }
                        )
                    entry.update(
                        type="relation", choices=choices, truncated=count > 200
                    )
                elif isinstance(field, forms.ChoiceField):
                    entry.update(
                        type="choice",
                        choices=[
                            {"value": str(k), "label": str(v)} for k, v in field.choices
                        ],
                    )
                elif isinstance(field, forms.DateTimeField):
                    entry["type"] = "datetime-local"
                    entry["help"] = (
                        entry["help"]
                        + " Clinic time: "
                        + timezone.get_current_timezone_name()
                    ).strip()
                elif isinstance(field, forms.DateField):
                    entry["type"] = "date"
                elif isinstance(field, forms.BooleanField):
                    entry["type"] = "checkbox"
                elif isinstance(field, (forms.DecimalField, forms.IntegerField)):
                    entry.update(
                        type="number",
                        step=(
                            "1"
                            if isinstance(field, forms.IntegerField)
                            and not isinstance(field, forms.DecimalField)
                            else "any"
                        ),
                    )
                elif isinstance(field.widget, forms.Textarea):
                    entry["type"] = "textarea"
                else:
                    entry["type"] = "text"
                fields.append(entry)
            schemas.append({"slug": slug, "title": title, "fields": fields})
        return response(
            {
                "schemas": schemas,
                "grant": grant,
                "prepared_at": timezone.now().isoformat(),
                "expires_in_days": 7,
                "patients": [
                    {"id": p.pk, "label": f"{p} · {p.medical_record_id}"}
                    for p in patients
                ],
            }
        )
    except ValidationError as exc:
        return response({"error": "; ".join(exc.messages)}, 400)


@require_POST
def sync(request):
    try:
        data = json_body(request)
        # Successful requests are idempotent even after their snapshot token expires.
        payload_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
        client_id = uuid.UUID(str(data.get("client_id", "")))
        with transaction.atomic():
            device = device_for(request, data.get("device_id"), lock=True)
            receipt = OfflineReceipt.objects.filter(
                device=device, client_id=client_id
            ).first()
            if receipt:
                if receipt.payload_hash != payload_hash:
                    return response(
                        {
                            "error": "This submission ID already identifies different content."
                        },
                        409,
                    )
                return response(
                    {
                        "record_id": receipt.record_id,
                        "model": receipt.model_label,
                        "replayed": True,
                    }
                )
            grant = signing.loads(data.get("grant", ""), salt=SALT, max_age=MAX_AGE)
            if (
                grant.get("device") != str(device.pk)
                or grant.get("user") != request.user.pk
            ):
                raise PermissionDenied
            slug = data.get("slug")
            if slug not in OFFLINE_MODULES:
                raise PermissionDenied("This operation requires a connected workspace.")
            model, title, names, scope, roles = MODULES[slug]
            if not allowed(request.user, roles):
                raise PermissionDenied
            values = data.get("values", {})
            proofs = data.get("proofs", {})
            if (
                not isinstance(values, dict)
                or not isinstance(proofs, dict)
                or any(
                    k not in names or not isinstance(v, (str, bool))
                    for k, v in values.items()
                )
            ):
                raise ValidationError("Invalid draft fields.")
            local = copy.copy(request)
            local.POST = QueryDict("", mutable=True)
            local._files = MultiValueDict()
            for key, value in values.items():
                local.POST[key] = (
                    str(value)
                    if not isinstance(value, bool)
                    else ("on" if value else "")
                )
            form = restrict(
                collection_form(local, model, names),
                grant["patients"],
                device.facility_id,
            )
            # Lock and compare all referenced rows; do not silently apply stale care context.
            for name, field in sorted(form.fields.items()):
                if isinstance(field, forms.ModelChoiceField) and values.get(name):
                    proof = signing.loads(
                        proofs.get(name, ""), salt=SALT, max_age=MAX_AGE
                    )
                    if (
                        proof.get("device") != str(device.pk)
                        or proof.get("slug") != slug
                        or proof.get("field") != name
                        or str(proof.get("pk")) != str(values[name])
                        or proof.get("model") != field.queryset.model._meta.label_lower
                    ):
                        raise PermissionDenied("Invalid record proof.")
                    parent = (
                        Patient.objects.select_for_update()
                        .filter(
                            pk=proof.get("patient_pk"),
                            facility_id=device.facility_id,
                            merged_into__isnull=True,
                        )
                        .first()
                    )
                    if parent is None or digest(parent) != proof.get("patient_digest"):
                        return response(
                            {
                                "error": "Patient identity changed since download. Refresh online and review the draft.",
                                "conflict": True,
                            },
                            409,
                        )
                    obj = (
                        field.queryset.select_for_update(of=("self",))
                        .filter(pk=proof["pk"])
                        .first()
                    )
                    if obj is None or digest(obj) != proof.get("digest"):
                        return response(
                            {
                                "error": f"{field.label or name} changed since download. Refresh online, review the draft and submit again.",
                                "conflict": True,
                            },
                            409,
                        )
            if not form.is_valid():
                return response(
                    {
                        "error": "Review the draft fields.",
                        "fields": form.errors.get_json_data(),
                    },
                    422,
                )
            raw_time = data.get("client_created_at")
            if not isinstance(raw_time, str):
                raise ValidationError("A device draft timestamp is required.")
            client_time = forms.DateTimeField().clean(raw_time)
            if client_time > timezone.now() + timedelta(minutes=5):
                raise ValidationError(
                    "Device timestamp is in the future. Check the device clock and review the draft."
                )
            obj = save_collection_form(form, request.user)
            OfflineReceipt.objects.create(
                device=device,
                client_id=client_id,
                payload_hash=payload_hash,
                client_created_at=client_time,
                model_label=obj._meta.label_lower,
                record_id=obj.pk,
            )
            return response(
                {
                    "record_id": obj.pk,
                    "model": obj._meta.label_lower,
                    "replayed": False,
                },
                201,
            )
    except (signing.BadSignature, TypeError):
        return response(
            {
                "error": "Downloaded context expired or is invalid. Refresh online and review the draft.",
                "conflict": True,
            },
            409,
        )
    except (ValidationError, ValueError) as exc:
        return response(
            {
                "error": (
                    "; ".join(exc.messages)
                    if isinstance(exc, ValidationError)
                    else "Invalid draft identifier."
                )
            },
            422,
        )
    except IntegrityError:
        return response(
            {
                "error": "A conflicting record already exists. Review it online.",
                "conflict": True,
            },
            409,
        )
