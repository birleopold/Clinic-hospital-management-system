"""Owner-only operational records. Never store clinical data or credentials here."""
import uuid
from django.db import models
from django.core.validators import MaxLengthValidator

CHECKPOINTS = [
    ('isolation', 'Isolated application and storage'),
    ('https', 'HTTPS and private network reviewed'),
    ('recovery', 'Backup and restore rehearsal'),
    ('administrator', 'Tenant administrator and MFA ready'),
    ('services', 'Services and branding reviewed'),
    ('staff', 'Staff roles and workstations checked'),
    ('acceptance', 'Tenant workflow acceptance recorded'),
]


class TenantReadinessCheck(models.Model):
    tenant = models.ForeignKey('accounts.TenantDeployment', on_delete=models.PROTECT, related_name='readiness_checks')
    step = models.CharField(max_length=24, choices=CHECKPOINTS)
    status = models.CharField(max_length=16, default='pending', choices=[('pending', 'Needs review'), ('verified', 'Operator verified')])
    evidence = models.CharField(max_length=500)
    updated_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'step'], name='tenant_readiness_unique_step')]


class TenantSupportCase(models.Model):
    tenant = models.ForeignKey('accounts.TenantDeployment', on_delete=models.PROTECT, related_name='support_cases')
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=24, choices=[('onboarding', 'Onboarding'), ('access', 'Access'), ('configuration', 'Configuration'), ('incident', 'Incident'), ('other', 'Other')])
    priority = models.CharField(max_length=16, default='normal', choices=[('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')])
    status = models.CharField(max_length=16, default='open', choices=[('open', 'Open'), ('in_progress', 'In progress'), ('waiting', 'Waiting on tenant'), ('resolved', 'Resolved')])
    detail = models.TextField(max_length=2000, validators=[MaxLengthValidator(2000)])
    resolution = models.TextField(max_length=2000, blank=True, validators=[MaxLengthValidator(2000)])
    assignee = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    created_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=['tenant', 'status'], name='tenant_case_status_idx')]


class TenantActivity(models.Model):
    tenant = models.ForeignKey('accounts.TenantDeployment', on_delete=models.PROTECT, related_name='activities')
    case = models.ForeignKey(TenantSupportCase, on_delete=models.PROTECT, null=True, blank=True, related_name='activities')
    actor = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True)
    event = models.CharField(max_length=60)
    summary = models.CharField(max_length=600)
    created_at = models.DateTimeField(auto_now_add=True)
    request_id = models.UUIDField(null=True, blank=True, unique=True)
    request_payload = models.JSONField(default=dict, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']

    def get_event_display(self):
        return {
            'tenant_registered': 'Workspace registered',
            'tenant_metadata_updated': 'Business details updated',
            'tenant_configuration_updated': 'Initial configuration updated',
            'tenant_readiness_updated': 'Readiness evidence updated',
            'tenant_case_opened': 'Support case opened',
            'tenant_case_updated': 'Support case updated',
            'tenant_policy_changed': 'Lifecycle policy changed',
            'tenant_bundle_downloaded': 'Protected bundle downloaded',
            'tenant_support_ticket_issued': 'Temporary support ticket issued',
            'tenant_first_contact': 'First authenticated tenant contact',
        }.get(self.event, self.event.replace('_', ' ').capitalize())
