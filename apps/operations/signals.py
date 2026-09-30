from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError


@receiver(pre_save)
def reject_archived_identity(sender, instance, **kwargs):
    if (
        kwargs.get("raw")
        or not instance._state.adding
        or sender.__name__.startswith("Historical")
    ):
        return
    from apps.demographics.models import Patient

    field = next(
        (
            f
            for f in sender._meta.fields
            if f.name == "patient" and f.is_relation and f.related_model is Patient
        ),
        None,
    )
    if (
        field
        and instance.patient_id
        and Patient.objects.filter(
            pk=instance.patient_id, merged_into__isnull=False
        ).exists()
    ):
        raise ValidationError(
            "Patient identity was merged. Select its canonical record."
        )
