from django.core.management.base import BaseCommand
from decimal import Decimal

from apps.billing.models import PriceList, PriceListItem
from apps.inventory.models import InventoryItem, Batch

PRICELIST_NAME = 'Default'

SERVICES = [
    ('CBC', 'Complete Blood Count', Decimal('15000.00')),
    ('UA', 'Urinalysis', Decimal('10000.00')),
    ('XR-CH', 'X-Ray Chest', Decimal('25000.00')),
]

DRUGS = [
    ('AMOX-500', 'Amoxicillin 500mg cap', Decimal('2000.00'), Decimal('500.00')),
    ('PCT-500', 'Paracetamol 500mg tab', Decimal('5000.00'), Decimal('1000.00')),
]

class Command(BaseCommand):
    help = 'Seed demo price list and inventory items for quick testing.'

    def handle(self, *args, **options):
        pl, _ = PriceList.objects.get_or_create(name=PRICELIST_NAME, defaults={'is_active': True})
        if not pl.is_active:
            pl.is_active = True
            pl.save(update_fields=['is_active'])
        created_items = 0
        for code, name, amount in SERVICES:
            _, created = PriceListItem.objects.get_or_create(
                pricelist=pl, code=code,
                defaults={'name': name, 'amount': amount, 'active': True}
            )
            if created:
                created_items += 1
        for code, name, amount, initial_qty in DRUGS:
            item, _ = InventoryItem.objects.get_or_create(code=code, defaults={'name': name})
            Batch.objects.get_or_create(item=item, batch_no='B001', defaults={'quantity_on_hand': initial_qty})
            _, created = PriceListItem.objects.get_or_create(
                pricelist=pl, code=code,
                defaults={'name': name, 'amount': amount, 'active': True}
            )
            if created:
                created_items += 1
        self.stdout.write(self.style.SUCCESS(f'Seeded {created_items} price list items and ensured inventory setup.'))
