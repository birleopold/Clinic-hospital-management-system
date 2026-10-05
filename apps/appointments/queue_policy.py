"""One department policy for queue actions and ordinary API edits."""
SERVICE_ROLES = {
    'triage': 'nurse', 'consult': 'clinician', 'lab': 'lab',
    'pharmacy': 'pharmacy', 'cashier': 'cashier',
}


def can_work_queue(user, service):
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or user.role == 'admin' or user.role == SERVICE_ROLES.get(service)
    ))
