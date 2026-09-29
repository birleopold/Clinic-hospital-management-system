from django.core.management.base import BaseCommand
from decimal import Decimal

from django.contrib.auth import get_user_model
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.orders.models import Order
from apps.pharmacy.models import Dispense
from apps.billing.models import PriceList, PriceListItem

class Command(BaseCommand):
    help = 'Seed a demo patient, one order (CBC) and one dispense (Paracetamol) to demonstrate auto-billing.'

    def handle(self, *args, **options):
        # Ensure seed_demo has run
        pl = PriceList.objects.filter(is_active=True).first()
        if not pl:
            self.stderr.write('Run `python manage.py seed_demo` first to create default pricelist and items.')
            return
        need_codes = {'CBC', 'PCT-500'}
        existing = set(PriceListItem.objects.filter(pricelist=pl, code__in=need_codes).values_list('code', flat=True))
        if not need_codes.issubset(existing):
            self.stderr.write('Pricelist missing required codes (CBC, PCT-500). Run `python manage.py seed_demo` again.')
            return

        # Create demo clinician
        User = get_user_model()
        clinician, _ = User.objects.get_or_create(username='clinician', defaults={'role': 'clinician'})
        # Create patient
        patient, _ = Patient.objects.get_or_create(
            first_name='Jane', last_name='Doe', gender='F', phone='0770000000'
        )
        enc = (
            Encounter.objects.filter(patient=patient, status=Encounter.OPEN)
            .order_by('-id')
            .first()
        )
        if not enc:
            enc = Encounter.objects.create(
                patient=patient, clinician=clinician, chief_complaint='Demo visit'
            )
        # Create a lab order (CBC) tied to the visit for EHR / labs queue
        order = Order.objects.create(
            patient=patient,
            encounter=enc,
            order_type=Order.LAB,
            code='CBC',
            description='Complete Blood Count',
            quantity=1,
        )
        # Create a dispense (Paracetamol)
        Dispense.objects.create(
            patient=patient, item_code='PCT-500', item_name='Paracetamol 500mg tab', quantity=Decimal('2')
        )
        self.stdout.write(self.style.SUCCESS(f'Demo data created for patient #{patient.id}.'))
