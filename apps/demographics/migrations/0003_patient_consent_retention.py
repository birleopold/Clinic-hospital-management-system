# Patient consent + retention fields (DPPA-oriented record-keeping).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('demographics', '0002_patient_facility'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='consent_data_processing',
            field=models.BooleanField(
                default=False,
                help_text='Patient consents to processing of personal data for care and billing (DPPA-style record).',
            ),
        ),
        migrations.AddField(
            model_name='patient',
            name='consent_recorded_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When consent was last recorded as granted.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='patient',
            name='data_retention_until',
            field=models.DateField(
                blank=True,
                help_text='Optional policy date after which inactive records may be archived or deleted per clinic SOP.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='historicalpatient',
            name='consent_data_processing',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='historicalpatient',
            name='consent_recorded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='historicalpatient',
            name='data_retention_until',
            field=models.DateField(blank=True, null=True),
        ),
    ]
