from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0003_encounter_facility'),
    ]

    operations = [
        migrations.AddField(
            model_name='diagnosis',
            name='coding_system',
            field=models.CharField(
                choices=[
                    ('ICD10', 'ICD-10'),
                    ('WHO_MOH', 'WHO / MoH coded (e.g. HMIS condition list)'),
                    ('LOCAL', 'Local clinic code'),
                ],
                default='ICD10',
                help_text='Code list used for HMIS / MoH reporting alignment.',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='historicaldiagnosis',
            name='coding_system',
            field=models.CharField(
                choices=[
                    ('ICD10', 'ICD-10'),
                    ('WHO_MOH', 'WHO / MoH coded (e.g. HMIS condition list)'),
                    ('LOCAL', 'Local clinic code'),
                ],
                default='ICD10',
                max_length=16,
            ),
        ),
    ]
