from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Order
from apps.billing import services as billing_services


@receiver(pre_save, sender=Order)
def order_track_previous_status(sender, instance: Order, **kwargs):
    if not instance.pk:
        instance._prev_order_status = None
        return
    try:
        prev = Order.objects.only('status').get(pk=instance.pk)
        instance._prev_order_status = prev.status
    except Order.DoesNotExist:
        instance._prev_order_status = None


@receiver(post_save, sender=Order)
def order_auto_billing(sender, instance: Order, created, **kwargs):
    if not created or not instance.billable:
        return
    billing_services.add_line_from_order(instance)


@receiver(post_save, sender=Order)
def order_cancel_invoice_reversal(sender, instance: Order, created, **kwargs):
    if created:
        return
    prev = getattr(instance, '_prev_order_status', None)
    if prev != Order.ORDERED or instance.status != Order.CANCELLED:
        return
    if not instance.billable:
        return
    billing_services.reverse_line_from_order(instance)
