from django.db import models
from django.db.models import Q, F
from .models import Record


class ManagementCase(Record):
    created_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    source_grant=models.ForeignKey('operations.PortalGrant',null=True,blank=True,on_delete=models.PROTECT,related_name='feedback')
    submission_key=models.UUIDField(null=True,blank=True,unique=True)
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    kind=models.CharField(max_length=16,choices=[('incident','Incident'),('complaint','Complaint')])
    severity=models.CharField(max_length=12,choices=[('low','Low'),('moderate','Moderate'),('high','High'),('critical','Critical')])
    title=models.CharField(max_length=160)
    details=models.TextField(help_text='Restricted manager register. Use record references; avoid copying clinical notes.')
    owner=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    due_at=models.DateTimeField()
    status=models.CharField(max_length=12,default='open',choices=[('open','Open'),('review','Awaiting closure review'),('closed','Closed')])
    resolution=models.TextField(blank=True)
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
    revision=models.PositiveIntegerField(default=1)


class CorrectiveAction(Record):
    case=models.ForeignKey(ManagementCase,on_delete=models.PROTECT,related_name='actions')
    owner=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    description=models.TextField()
    due_at=models.DateTimeField()
    completed_at=models.DateTimeField(null=True,blank=True)
    evidence=models.TextField(blank=True)


class FacilityAsset(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    tag=models.CharField(max_length=80)
    name=models.CharField(max_length=160)
    serial_number=models.CharField(max_length=120,blank=True)
    location=models.CharField(max_length=160)
    custodian=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    status=models.CharField(max_length=16,default='operational',choices=[('operational','Operational'),('out_of_service','Out of service'),('retired','Retired')])
    maintenance_due=models.DateField(null=True,blank=True)
    calibration_due=models.DateField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['facility','tag'],name='unique_facility_asset_tag')]
    def __str__(self):return f'{self.tag} · {self.name}'


class AssetEvent(Record):
    asset=models.ForeignKey(FacilityAsset,on_delete=models.PROTECT,related_name='events')
    kind=models.CharField(max_length=16,choices=[('maintenance','Maintenance'),('calibration','Calibration'),('downtime','Downtime'),('restore','Restore service'),('retire','Retire')])
    vendor=models.CharField(max_length=160,blank=True)
    cost=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    evidence=models.TextField()
    next_due=models.DateField(null=True,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(cost__gte=0),name='asset_nonnegative_cost')]


class StaffChecklist(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    staff=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    owner=models.ForeignKey('accounts.User',on_delete=models.PROTECT,related_name='+')
    kind=models.CharField(max_length=16,choices=[('onboarding','Onboarding'),('offboarding','Offboarding'),('training','Training'),('policy','Policy acknowledgment')])
    title=models.CharField(max_length=160)
    version=models.CharField(max_length=80,blank=True,help_text='Required for policies and training; retain the source document reference.')
    instructions=models.TextField()
    due_at=models.DateTimeField()
    completed_at=models.DateTimeField(null=True,blank=True)
    evidence=models.TextField(blank=True)
    acknowledged_at=models.DateTimeField(null=True,blank=True)
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)


class OperatingBudget(Record):
    facility=models.ForeignKey('accounts.Facility',on_delete=models.PROTECT)
    cost_centre=models.CharField(max_length=120)
    starts_on=models.DateField()
    ends_on=models.DateField()
    amount=models.DecimalField(max_digits=14,decimal_places=2)
    status=models.CharField(max_length=12,default='draft',choices=[('draft','Draft'),('approved','Approved'),('rejected','Rejected')])
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0,ends_on__gte=F('starts_on')),name='valid_operating_budget')]
    def __str__(self):return f'{self.cost_centre} · {self.starts_on}–{self.ends_on}'


class OperatingExpense(Record):
    budget=models.ForeignKey(OperatingBudget,on_delete=models.PROTECT,related_name='expenses')
    incurred_on=models.DateField()
    payee=models.CharField(max_length=160)
    reference=models.CharField(max_length=120,help_text='Supplier invoice / receipt reference. Unique within this budget.')
    description=models.TextField()
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=12,default='requested',choices=[('requested','Requested'),('approved','Approved'),('rejected','Rejected')])
    reviewed_by=models.ForeignKey('accounts.User',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=250,blank=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='positive_operating_expense'),models.UniqueConstraint(fields=['budget','payee','reference'],name='unique_expense_reference')]


class ExpenseSettlement(Record):
    """Evidence of a disbursement; independent reconciliation posts it to reports."""
    expense = models.ForeignKey(OperatingExpense, on_delete=models.PROTECT, related_name='settlements')
    request_key = models.UUIDField(unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=[('bank', 'Bank transfer'), ('mobile_money', 'Mobile money'), ('petty_cash', 'Separate petty-cash account')])
    account_reference = models.CharField(max_length=100)
    transaction_reference = models.CharField(max_length=120)
    evidence = models.TextField()
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Awaiting reconciliation'), ('confirmed', 'Reconciled'), ('rejected', 'Rejected evidence')])
    reconciled_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reconciled_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=250, blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_expense_settlement')]
