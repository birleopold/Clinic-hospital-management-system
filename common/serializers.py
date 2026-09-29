"""Apply the same facility scope to writable relations as to list/detail queries."""
from rest_framework import serializers

from common.facility_scope import is_superuser, user_staff_facility_id


class FacilityScopedSerializer(serializers.ModelSerializer):
    relation_scopes = {
        'accounts.facility': 'pk',
        'accounts.user': 'staff_profile__facility_id',
        'demographics.patient': 'facility_id',
        'encounters.encounter': 'facility_id',
        'appointments.appointment': 'patient__facility_id',
        'orders.order': 'patient__facility_id',
        'pharmacy.prescription': 'patient__facility_id',
        'pharmacy.prescriptionitem': 'prescription__patient__facility_id',
        'billing.invoice': 'patient__facility_id',
    }

    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        fid = user_staff_facility_id(user)
        if is_superuser(user):
            return fields
        for field in fields.values():
            qs = getattr(field, 'queryset', None)
            if qs is not None and not field.read_only:
                lookup = self.relation_scopes.get(qs.model._meta.label_lower)
                if lookup:
                    field.queryset = qs.filter(**{lookup: fid}) if fid is not None else qs.none()
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Check the resulting state, including relations retained during PATCH.
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        patient = value('patient')
        for name in ('encounter', 'appointment'):
            related = value(name)
            if patient and related and related.patient_id != patient.pk:
                raise serializers.ValidationError({name: 'Must belong to the selected patient.'})
        item = value('prescription_item')
        if item:
            if patient and item.prescription.patient_id != patient.pk:
                raise serializers.ValidationError({'prescription_item': 'Must belong to the selected patient.'})
            if value('item_code') != item.item_code:
                raise serializers.ValidationError({'item_code': 'Must match the prescription item.'})
        return attrs
