import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


FINANCIAL_OPERATIONS = [
    ('purchase', 'Purchase orders'), ('budget', 'Operating budgets'),
    ('expense', 'Operating expenses'), ('settlement', 'Expense reconciliation'),
    ('credit', 'Invoice credits'), ('refund', 'Cash refund authorization'),
    ('return', 'Medicine returns'), ('price', 'Basket price changes'),
]
WORKFORCE_OPERATIONS = [
    ('attendance_review', 'Attendance review'), ('leave_review', 'Leave review'),
    ('cover_review', 'Cover and swap review'), ('roster_publish', 'Roster publication'),
]
# Existing monetary policy callers intentionally retain only financial workflows.
OPERATIONS = FINANCIAL_OPERATIONS


class ApprovalPolicy(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    operation = models.CharField(max_length=20, choices=FINANCIAL_OPERATIONS)
    enabled = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['facility', 'operation'], name='one_facility_approval_policy')]


class ApprovalGrant(models.Model):
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    facility = models.ForeignKey('accounts.Facility', on_delete=models.PROTECT)
    operation = models.CharField(max_length=20, choices=FINANCIAL_OPERATIONS + WORKFORCE_OPERATIONS)
    approver = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='approval_grants')
    maximum = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=250)
    created_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(
                models.Q(operation__in=[key for key, _ in FINANCIAL_OPERATIONS], maximum__isnull=False, maximum__gte=0, maximum__lte=Decimal('999999999999.99'))
                | models.Q(operation__in=[key for key, _ in WORKFORCE_OPERATIONS], maximum__isnull=True)
            ),
            name='approval_grant_operation_limit',
        )]

    def clean(self):
        super().clean()
        if self.operation in dict(WORKFORCE_OPERATIONS):
            if self.maximum is not None:
                raise ValidationError({'maximum': 'Workforce authority has no monetary limit.'})
        elif self.operation in dict(FINANCIAL_OPERATIONS):
            try:
                amount = Decimal(self.maximum)
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError({'maximum': 'Set a finite, nonnegative UGX limit.'})
            if not amount.is_finite() or amount < 0:
                raise ValidationError({'maximum': 'Set a finite, nonnegative UGX limit.'})

    @property
    def is_workforce(self):
        return self.operation in dict(WORKFORCE_OPERATIONS)

    @property
    def authority_status(self):
        if self.revoked_at:
            return 'revoked'
        now = timezone.now()
        if self.starts_at > now:
            return 'scheduled'
        if self.ends_at <= now:
            return 'expired'
        return 'active'
