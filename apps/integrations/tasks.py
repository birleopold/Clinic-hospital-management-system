from celery import shared_task


@shared_task(name='integrations.health_ping')
def health_ping() -> str:
    """Cheap task to verify worker connectivity."""
    return 'pong'
