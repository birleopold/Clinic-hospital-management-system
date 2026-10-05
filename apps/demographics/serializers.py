from django.utils import timezone
from rest_framework import serializers
from common.serializers import FacilityScopedSerializer
from common.facility_scope import user_staff_facility_id
from .models import Patient


class PatientSerializer(FacilityScopedSerializer):
    class Meta:
        model = Patient
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = getattr(self.context.get('request'), 'user', None)
        fid = user_staff_facility_id(user)
        if not getattr(user, 'is_superuser', False) and fid is None:
            raise serializers.ValidationError({'facility': 'Ask an administrator to assign your staff facility.'})
        if fid and not user.is_superuser and 'facility' in attrs and attrs['facility'] is None:
            raise serializers.ValidationError({'facility': 'Your facility cannot be cleared.'})
        return attrs

    def create(self, validated_data):
        if validated_data.get('consent_data_processing') and not validated_data.get('consent_recorded_at'):
            validated_data['consent_recorded_at'] = timezone.now()
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if user and 'facility' not in validated_data:
            fid = user_staff_facility_id(user)
            if fid:
                validated_data['facility_id'] = fid
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'consent_data_processing' in validated_data:
            new = validated_data['consent_data_processing']
            old = instance.consent_data_processing
            if new and not old:
                validated_data['consent_recorded_at'] = timezone.now()
            elif not new:
                validated_data['consent_recorded_at'] = None
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if (
            user
            and instance.facility_id is None
            and 'facility' not in validated_data
            and 'facility_id' not in validated_data
        ):
            fid = user_staff_facility_id(user)
            if fid:
                validated_data['facility_id'] = fid
        return super().update(instance, validated_data)


class PatientIdentitySerializer(serializers.ModelSerializer):
    """The identity fields shown by the shared patient search and chart banner."""

    class Meta:
        model = Patient
        fields = (
            'id', 'medical_record_id', 'first_name', 'last_name', 'other_names',
            'gender', 'date_of_birth', 'phone', 'facility',
        )
        read_only_fields = fields
