import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from common.facility_scope import filter_by_facility
from . import approval_services as service
from .approval_models import FINANCIAL_OPERATIONS, WORKFORCE_OPERATIONS
from .models import ApprovalGrant, ApprovalPolicy, Facility, OwnerSupportReceipt, User


class BaseGrantForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    operations = ()
    workforce = False

    class Meta:
        model = ApprovalGrant
        fields = ['facility', 'operation', 'approver', 'starts_at', 'ends_at', 'reason']
        widgets = {
            'facility': forms.HiddenInput,
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, actor=None, facilities=None, **kwargs):
        super().__init__(*args, **kwargs)
        if facilities is None:
            facilities = filter_by_facility(Facility.objects.filter(is_active=True), actor, field='pk')
        if self.workforce:
            facilities = service.workforce_facilities(facilities)
        self.fields['facility'].queryset = facilities
        self.fields['operation'].choices = self.operations
        selected = self.data.get(self.add_prefix('facility')) if self.is_bound else self.initial.get('facility')
        selected = getattr(selected, 'pk', selected)
        try:
            selected_facilities = facilities.filter(pk=selected) if selected else facilities.none()
        except (TypeError, ValueError):
            selected_facilities = facilities.none()
        if self.workforce:
            users = service.workforce_recipients(selected_facilities)
        else:
            users = User.objects.filter(is_active=True, role__in=['admin', 'manager'], staff_profile__facility__in=selected_facilities).exclude(
                pk__in=OwnerSupportReceipt.objects.values('user_id')
            )
        self.fields['approver'].queryset = users.exclude(pk=getattr(actor, 'pk', None)).order_by('username')

    def clean(self):
        data = super().clean()
        if self.workforce and self.data.get(self.add_prefix('maximum')) not in (None, ''):
            raise ValidationError('Workforce authority has no monetary limit.')
        return data


class FinancialGrantForm(BaseGrantForm):
    operations = FINANCIAL_OPERATIONS
    maximum = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label='Maximum approved amount · UGX')

    class Meta(BaseGrantForm.Meta):
        fields = ['facility', 'operation', 'approver', 'maximum', 'starts_at', 'ends_at', 'reason']


# Preserve the existing public form name and financial POST action.
GrantForm = FinancialGrantForm


class WorkforceGrantForm(BaseGrantForm):
    operations = WORKFORCE_OPERATIONS
    workforce = True


@login_required
@never_cache
def matrix(request):
    actor = service.administrator(request.user)
    facilities = filter_by_facility(Facility.objects.filter(is_active=True), actor, field='pk').order_by('name', 'pk')
    selection = request.POST.get('facility') if request.method == 'POST' else request.GET.get('facility')
    try:
        selected_facility = facilities.filter(pk=selection).first() if selection else facilities.first()
    except (TypeError, ValueError):
        selected_facility = None
    action = request.POST.get('action') if request.method == 'POST' else None
    initial = {'facility': selected_facility, 'request_key': uuid.uuid4()}
    form = FinancialGrantForm(request.POST if action == 'grant' else None, actor=actor, facilities=facilities, initial=initial, auto_id='financial_%s')
    workforce_form = WorkforceGrantForm(request.POST if action == 'workforce_grant' else None, actor=actor, facilities=facilities,
                                       initial={**initial, 'request_key': uuid.uuid4()}, auto_id='workforce_%s')
    if request.method == 'POST':
        try:
            if action in ('grant', 'workforce_grant'):
                submitted = workforce_form if action == 'workforce_grant' else form
                if not submitted.is_valid():
                    raise ValidationError('Correct the grant fields below.')
                service.grant(actor, **submitted.cleaned_data)
            elif action == 'policy':
                facility = get_object_or_404(facilities, pk=request.POST.get('facility'))
                service.configure(actor, facility.pk, request.POST.get('operation'), request.POST.get('enabled') == '1',
                                  int(request.POST.get('revision', '0')), request.POST.get('reason', ''))
            elif action == 'revoke':
                obj = get_object_or_404(filter_by_facility(ApprovalGrant.objects.all(), actor), pk=request.POST.get('grant'))
                service.revoke(actor, obj.pk, request.POST.get('reason', ''))
            else:
                raise ValidationError('Choose a supported approval matrix action.')
        except (ValidationError, ValueError, IntegrityError) as exc:
            messages.error(request, '; '.join(exc.messages) if isinstance(exc, ValidationError)
                           else 'Changed or duplicate authority. Reload and review the existing grant.')
        else:
            return redirect('approval-matrix')
    policies = {(p.facility_id, p.operation): p for p in ApprovalPolicy.objects.filter(facility__in=facilities)}
    rows = [{'facility': f, 'operation': key, 'label': label, 'policy': policies.get((f.pk, key))}
            for f in facilities for key, label in FINANCIAL_OPERATIONS]
    grants = filter_by_facility(ApprovalGrant.objects.select_related('facility', 'approver', 'created_by'), actor).order_by('-pk')
    return render(request, 'accounts/approval_matrix.html', {
        'form': form, 'workforce_form': workforce_form, 'rows': rows,
        'facilities': facilities, 'selected_facility': selected_facility,
        'workforce_enabled': bool(selected_facility and service.workforce_enabled(selected_facility.pk)),
        'page': Paginator(grants, 25).get_page(request.GET.get('page')),
    })
