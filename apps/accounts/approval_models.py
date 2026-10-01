import uuid
from django.db import models

OPERATIONS=[('purchase','Purchase orders'),('budget','Operating budgets'),('expense','Operating expenses'),('settlement','Expense reconciliation'),('credit','Invoice credits'),('refund','Cash refund authorization'),('return','Medicine returns'),('price','Basket price changes')]

class ApprovalPolicy(models.Model):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    operation=models.CharField(max_length=20,choices=OPERATIONS)
    enabled=models.BooleanField(default=False)
    revision=models.PositiveIntegerField(default=1)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','operation'],name='one_facility_approval_policy')]

class ApprovalGrant(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    operation=models.CharField(max_length=20,choices=OPERATIONS)
    approver=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='approval_grants')
    maximum=models.DecimalField(max_digits=14,decimal_places=2)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    reason=models.CharField(max_length=250)
    created_by=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    created_at=models.DateTimeField(auto_now_add=True)
    revoked_by=models.ForeignKey('accounts.User',on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    revoked_at=models.DateTimeField(null=True,blank=True)
    revocation_reason=models.CharField(max_length=250,blank=True)
