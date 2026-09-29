from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
import re
from datetime import date

from .models import Patient
from common.facility_scope import assign_facility_for_patient, filter_by_facility


ALLOWED_EDIT_ROLES = ('admin', 'reception')
ALLOWED_VIEW_ROLES = ('admin', 'reception', 'clinician')


def _apply_consent_and_retention(patient: Patient, post, prev_consent: bool) -> list:
    """Parse consent checkbox and retention date; return validation error strings."""
    errors = []
    consent = post.get('consent_data_processing') == '1'
    patient.consent_data_processing = consent
    if consent and not prev_consent:
        patient.consent_recorded_at = timezone.now()
    elif consent and patient.consent_recorded_at is None:
        patient.consent_recorded_at = timezone.now()
    elif not consent:
        patient.consent_recorded_at = None
    retention_str = (post.get('data_retention_until') or '').strip()
    if retention_str:
        try:
            patient.data_retention_until = date.fromisoformat(retention_str)
        except ValueError:
            errors.append('Invalid data retention until date')
    else:
        patient.data_retention_until = None
    return errors


@login_required
def patient_list_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ALLOWED_VIEW_ROLES):
        return HttpResponseForbidden('Not allowed')
    q = (request.GET.get('q') or '').strip()
    qs = filter_by_facility(Patient.objects.all(), user).order_by('-id')
    if q:
        from django.db.models import Q
        try:
            pid = int(q)
        except Exception:
            pid = None
        flt = (
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(other_names__icontains=q) | Q(phone__icontains=q)
        )
        if pid is not None:
            flt = flt | Q(id=pid)
        qs = qs.filter(flt)
    context = {
        'patients': qs[:200],
        'q': q,
    }
    return render(request, 'demographics/patient_list.html', context)


@login_required
def patient_create_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ALLOWED_EDIT_ROLES):
        return HttpResponseForbidden('Not allowed')
    if request.method == 'POST':
        p = Patient(
            first_name=(request.POST.get('first_name') or '').strip(),
            last_name=(request.POST.get('last_name') or '').strip(),
            other_names=(request.POST.get('other_names') or '').strip(),
            gender=(request.POST.get('gender') or '').strip()[:1],
            phone=(request.POST.get('phone') or '').strip(),
            email=(request.POST.get('email') or '').strip(),
            address=(request.POST.get('address') or '').strip(),
            insurance_provider=(request.POST.get('insurance_provider') or '').strip(),
            insurance_id=(request.POST.get('insurance_id') or '').strip(),
        )
        errors = []
        dob_str = (request.POST.get('date_of_birth') or '').strip()
        if dob_str:
            try:
                p.date_of_birth = date.fromisoformat(dob_str)
                if p.date_of_birth > date.today():
                    errors.append('Date of birth must be in the past')
            except Exception:
                errors.append('Invalid date of birth')
        # minimal name
        if not p.first_name and not p.last_name:
            errors.append('First or Last name is required')
        # phone format
        if p.phone:
            if not re.fullmatch(r"\+?\d{7,15}", p.phone):
                errors.append('Phone must be digits with optional leading + (7-15 digits)')
        # email format
        if p.email:
            try:
                validate_email(p.email)
            except ValidationError:
                errors.append('Email format is invalid')
        errors.extend(_apply_consent_and_retention(p, request.POST, prev_consent=False))
        # duplicate warning (do not block unless you want to confirm)
        dup_candidates = []
        if p.phone:
            dup_candidates = list(filter_by_facility(Patient.objects.all(), user).filter(phone=p.phone))
        confirm_duplicate = (request.POST.get('confirm_duplicate') == '1')
        if errors:
            return render(request, 'demographics/patient_form.html', {
                'patient': p, 'errors': errors, 'mode': 'create', 'dup_candidates': dup_candidates,
            })
        if dup_candidates and not confirm_duplicate:
            return render(request, 'demographics/patient_form.html', {
                'patient': p, 'mode': 'create', 'dup_candidates': dup_candidates, 'dup_warning': 'A patient with the same phone exists. Review below and confirm to proceed.'
            })
        assign_facility_for_patient(user, p)
        p.save()
        return redirect('patients-list')
    return render(request, 'demographics/patient_form.html', {'patient': None, 'mode': 'create'})


@login_required
def patient_edit_view(request, patient_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ALLOWED_EDIT_ROLES):
        return HttpResponseForbidden('Not allowed')
    p = get_object_or_404(filter_by_facility(Patient.objects.all(), user), pk=patient_id)
    # Prepare audit breadcrumbs
    first_hist = getattr(p, 'history', None).order_by('history_date').first() if hasattr(p, 'history') else None
    last_hist = getattr(p, 'history', None).order_by('-history_date').first() if hasattr(p, 'history') else None
    audit = {
        'created_at': p.created_at,
        'created_by': getattr(first_hist, 'history_user', None) if first_hist else None,
        'last_updated': p.updated_at,
        'last_updated_by': getattr(last_hist, 'history_user', None) if last_hist else None,
    }
    if request.method == 'POST':
        prev_consent = p.consent_data_processing
        p.first_name = (request.POST.get('first_name') or '').strip()
        p.last_name = (request.POST.get('last_name') or '').strip()
        p.other_names = (request.POST.get('other_names') or '').strip()
        p.gender = (request.POST.get('gender') or '').strip()[:1]
        p.phone = (request.POST.get('phone') or '').strip()
        p.email = (request.POST.get('email') or '').strip()
        p.address = (request.POST.get('address') or '').strip()
        p.insurance_provider = (request.POST.get('insurance_provider') or '').strip()
        p.insurance_id = (request.POST.get('insurance_id') or '').strip()
        errors = []
        dob_str = (request.POST.get('date_of_birth') or '').strip()
        if dob_str:
            try:
                p.date_of_birth = date.fromisoformat(dob_str)
                if p.date_of_birth > date.today():
                    errors.append('Date of birth must be in the past')
            except Exception:
                errors.append('Invalid date of birth')
        if not p.first_name and not p.last_name:
            errors.append('First or Last name is required')
        if p.phone:
            if not re.fullmatch(r"\+?\d{7,15}", p.phone):
                errors.append('Phone must be digits with optional leading + (7-15 digits)')
        if p.email:
            try:
                validate_email(p.email)
            except ValidationError:
                errors.append('Email format is invalid')
        errors.extend(_apply_consent_and_retention(p, request.POST, prev_consent=prev_consent))
        dup_candidates = []
        if p.phone:
            dup_candidates = list(filter_by_facility(Patient.objects.all(), user).filter(phone=p.phone).exclude(id=p.id))
        confirm_duplicate = (request.POST.get('confirm_duplicate') == '1')
        if errors:
            return render(request, 'demographics/patient_form.html', {'patient': p, 'errors': errors, 'mode': 'edit', 'audit': audit, 'dup_candidates': dup_candidates})
        if dup_candidates and not confirm_duplicate:
            return render(request, 'demographics/patient_form.html', {'patient': p, 'mode': 'edit', 'audit': audit, 'dup_candidates': dup_candidates, 'dup_warning': 'A patient with the same phone exists. Review below and confirm to proceed.'})
        assign_facility_for_patient(user, p)
        p.save()
        return redirect('patients-list')
    return render(request, 'demographics/patient_form.html', {'patient': p, 'mode': 'edit', 'audit': audit})
