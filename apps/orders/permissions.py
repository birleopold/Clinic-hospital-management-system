"""Shared result visibility for API reads and authenticated document downloads."""
from common.facility_scope import filter_by_patient_facility
from common.service_policy import enabled


RESULT_READ_ROLES = ('admin', 'clinician', 'lab', 'nurse')
RESULT_REVIEW_ROLES = ('admin', 'clinician', 'lab')


def can_review_unreleased_results(user):
    return bool(
        user and user.is_authenticated and user.is_active
        and (user.is_superuser or user.role in RESULT_REVIEW_ROLES)
    )


def filter_visible_results(queryset, user):
    """Keep permitted facility/services; only reviewers may see draft results."""
    if not (
        user and user.is_authenticated and user.is_active
        and (user.is_superuser or user.role in RESULT_READ_ROLES)
    ):
        return queryset.none()
    queryset = filter_by_patient_facility(queryset, user, prefix='order__patient__')
    for order_type, service in (
        ('lab', 'lab'), ('imaging', 'imaging'), ('procedure', 'clinical'),
    ):
        if not enabled(user, service):
            queryset = queryset.exclude(order__order_type=order_type)
    if not can_review_unreleased_results(user):
        queryset = queryset.filter(approved_at__isnull=False)
    return queryset
