"""Control-plane metadata only; tenant records live in independent databases."""
import uuid
from django.db import models
from django.core.validators import MaxLengthValidator

class TenantDeployment(models.Model):
    key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    name=models.CharField(max_length=160)
    origin=models.URLField(unique=True)
    bind_port=models.PositiveIntegerField(unique=True)
    service_type=models.CharField(max_length=20)
    services=models.JSONField(default=list)
    admin_username=models.CharField(max_length=150)
    state=models.CharField(max_length=20,default='provisioning',choices=[('provisioning','Awaiting deployment'),('active','Active'),('suspended','Suspended'),('retired','Retired')])
    secret_envelope=models.TextField(editable=False)
    created_by=models.ForeignKey('accounts.User',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    last_seen_at=models.DateTimeField(null=True,blank=True)
    revision=models.PositiveIntegerField(default=1)
    contact_name=models.CharField(max_length=160,blank=True)
    contact_email=models.EmailField(blank=True)
    contact_phone=models.CharField(max_length=40,blank=True)
    deployment_label=models.CharField(max_length=160,blank=True)
    operator_notes=models.TextField(max_length=2000,blank=True,validators=[MaxLengthValidator(2000)])
    bundle_generated_at=models.DateTimeField(null=True,blank=True)
    legacy_configuration_locked=models.BooleanField(default=False)

    @property
    def configuration_editable(self):
        return self.state=='provisioning' and not (self.legacy_configuration_locked or self.bundle_generated_at or self.last_seen_at)

    @property
    def health_label(self):
        from datetime import timedelta
        from django.utils import timezone
        if not self.last_seen_at:return 'No authenticated contact yet'
        if self.last_seen_at < timezone.now()-timedelta(minutes=10):return 'No recent authenticated contact'
        return 'Authenticated contact within 10 minutes'


class OwnerSupportReceipt(models.Model):
    nonce=models.UUIDField(unique=True)
    user=models.OneToOneField('accounts.User',on_delete=models.PROTECT)
    owner_reference=models.CharField(max_length=160)
    reason=models.CharField(max_length=250)
    expires_at=models.DateTimeField()
    revoked_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
