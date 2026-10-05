import uuid
from django import forms
from common.service_policy import SERVICES, PRESETS
from .models import TenantSupportCase
from .tenant_portal_models import CHECKPOINTS
from .tenant_portal_services import owner_assignees

CAUTION = 'Operational details only. Do not enter patient information, passwords, tokens or private keys.'


class WorkspaceForm(forms.Form):
    name = forms.CharField(max_length=160, label='Business name')
    origin = forms.URLField(label='Tenant HTTPS origin', assume_scheme='https')
    bind_port = forms.IntegerField(min_value=1024, max_value=65535, label='Private application port')
    admin_username = forms.CharField(max_length=150, label='Initial tenant administrator username')
    service_type = forms.ChoiceField(choices=[(k, k.title()) for k in PRESETS], label='Business service preset')
    services = forms.MultipleChoiceField(choices=[(key, value[0]) for key, value in SERVICES.items()], widget=forms.CheckboxSelectMultiple, help_text='Presets are starting points, not billing plans. Review the services this business actually offers.')


class RequestForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput)
    request_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class RevisionForm(RequestForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)


class ConfigurationForm(WorkspaceForm, RevisionForm):
    pass


class MetadataForm(RevisionForm):
    contact_name = forms.CharField(max_length=160, required=False, label='Business contact')
    contact_email = forms.EmailField(required=False)
    contact_phone = forms.CharField(max_length=40, required=False)
    deployment_label = forms.CharField(max_length=160, required=False, label='Operator deployment / host reference', help_text='A human-readable reference only; no connection credentials or automatic host enrollment.')
    operator_notes = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3}), help_text=CAUTION)


class ReadinessForm(RevisionForm):
    step = forms.ChoiceField(choices=CHECKPOINTS, widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=[('pending', 'Needs review'), ('verified', 'Operator verified')])
    evidence = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 2}), help_text=CAUTION+' Record who checked it, when, and a non-secret evidence reference.')


class LifecycleForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    request_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    reason = forms.CharField(max_length=250, help_text='Retirement is final in the portal; it retains records and does not delete or stop infrastructure.')


class SupportLaunchForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput, initial='support')
    reason = forms.CharField(max_length=250, help_text='Why is temporary access needed? '+CAUTION)


class CaseForm(RequestForm):
    title = forms.CharField(max_length=160)
    category = forms.ChoiceField(choices=TenantSupportCase._meta.get_field('category').choices)
    priority = forms.ChoiceField(choices=TenantSupportCase._meta.get_field('priority').choices, initial='normal')
    detail = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows': 3}), help_text=CAUTION)
    assignee = forms.ModelChoiceField(queryset=None, required=False, label='Assigned platform owner')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = owner_assignees()


class CaseUpdateForm(RevisionForm):
    def clean_action(self):
        if self.cleaned_data['action'] != 'update_case':raise forms.ValidationError('Reload this support case before saving.')
        return 'update_case'

    status = forms.ChoiceField(choices=TenantSupportCase._meta.get_field('status').choices)
    priority = forms.ChoiceField(choices=TenantSupportCase._meta.get_field('priority').choices)
    assignee = forms.ModelChoiceField(queryset=None, required=False, label='Assigned platform owner')
    resolution = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3}), help_text='Required when resolved. '+CAUTION)
    note = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 2}), help_text=CAUTION)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = owner_assignees()
