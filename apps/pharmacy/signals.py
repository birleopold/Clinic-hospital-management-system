from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Dispense
from apps.billing import services as billing_services
from apps.inventory.models import InventoryItem, StockMovement, Batch

@receiver(post_save, sender=Dispense)
def dispense_auto_billing(sender, instance: Dispense, created, **kwargs):
    if not created:
        return
    billing_services.add_line_from_dispense(instance)
    # Prefer the explicitly selected batch; else FEFO
    batch = getattr(instance, 'batch', None)
    item = None
    if batch and batch.item_id:
        item = batch.item
    else:
        try:
            item = InventoryItem.objects.get(code=instance.item_code)
        except InventoryItem.DoesNotExist:
            return
        batch = (
            Batch.objects
            .filter(item=item)
            .order_by('expiry', 'id')
            .first()
        )
    StockMovement.objects.create(
        item=item,
        batch=batch,
        direction=StockMovement.OUT,
        quantity=instance.quantity,
        reason='dispense',
        ref=f'dispense:{instance.id}'
    )
    if batch:
        # naive decrement; UI/API should validate sufficiency
        batch.quantity_on_hand = (batch.quantity_on_hand or 0) - instance.quantity
        batch.save(update_fields=['quantity_on_hand'])
