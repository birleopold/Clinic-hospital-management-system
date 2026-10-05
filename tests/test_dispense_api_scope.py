"""Automatic API batch selection must match the transactional stock policy."""
from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import Facility
from apps.inventory.models import Batch
from apps.operations.models import StockLocation
from apps.pharmacy.models import Dispense
from tests.test_suite import suite

pytestmark=pytest.mark.django_db


def test_api_automatic_batch_uses_usable_patient_facility_stock(suite):
    s=suite
    outside=StockLocation.objects.create(facility=Facility.objects.create(name='Other facility'),name='Other store')
    unavailable=[
        Batch.objects.create(item=s.i,location=outside,quantity_on_hand=200,expiry=timezone.localdate()+timedelta(days=1)),
        Batch.objects.create(item=s.i,location=s.l,quantity_on_hand=200,expiry=timezone.localdate()-timedelta(days=1)),
        Batch.objects.create(item=s.i,location=s.l,quantity_on_hand=200,expiry=timezone.localdate()+timedelta(days=2),quarantined=True),
    ]
    api=APIClient();api.force_authenticate(s.u)
    response=api.post('/api/dispenses/',{'patient':s.p.pk,'prescription_item':s.pi.pk,'item_code':s.i.code,'quantity':'2'})
    assert response.status_code==201,response.data
    assert Dispense.objects.get().batch_id==s.b.pk
    s.b.refresh_from_db()
    assert s.b.quantity_on_hand==8
    for batch in unavailable:
        batch.refresh_from_db()
        assert batch.quantity_on_hand==200


def test_api_shortage_does_not_count_or_disclose_other_facility_stock(suite):
    s=suite;s.b.quantity_on_hand=0;s.b.save()
    outside=StockLocation.objects.create(facility=Facility.objects.create(name='Other facility'),name='Other store')
    Batch.objects.create(item=s.i,location=outside,quantity_on_hand=731,expiry=timezone.localdate()+timedelta(days=1))
    api=APIClient();api.force_authenticate(s.u)
    response=api.post('/api/dispenses/',{'patient':s.p.pk,'prescription_item':s.pi.pk,'item_code':s.i.code,'quantity':'2'})
    assert response.status_code==400
    assert b'Available: 0' in response.content and b'731' not in response.content
    assert not Dispense.objects.exists()
