"""Control-plane metadata only; tenant records live in independent databases."""
import uuid
from django.db import models

class TenantDeployment(models.Model):
    key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    name=models.CharField(max_length=160)
    origin=models.URLField(unique=True)
    bind_port=models.PositiveIntegerField(unique=True)
    service_type=models.CharField(max_length=20)
    services=models.JSONField(default=list)
    admin_username=models.CharField(max_length=150)
    state=models.CharField(max_length=20,default='provisioning',choices=[('provisioning','Awaiting deployment'),('active','Active'),('suspended','Suspended')])
    secret_envelope=models.TextField(editable=False)
    created_by=models.ForeignKey('accounts.User',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    last_seen_at=models.DateTimeField(null=True,blank=True)
    revision=models.PositiveIntegerField(default=1)

class OwnerSupportReceipt(models.Model):
    nonce=models.UUIDField(unique=True)
    user=models.OneToOneField('accounts.User',on_delete=models.PROTECT)
    owner_reference=models.CharField(max_length=160)
    reason=models.CharField(max_length=250)
    expires_at=models.DateTimeField()
    revoked_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
