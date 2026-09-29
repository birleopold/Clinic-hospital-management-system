from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Encounter
from apps.billing import services as billing_services


@receiver(post_save, sender=Encounter)
def encounter_close_marks_invoices_ready(sender, instance: Encounter, created, **kwargs):
    if instance.status == Encounter.CLOSED:
        billing_services.ready_open_invoices_for_patient(instance.patient)
