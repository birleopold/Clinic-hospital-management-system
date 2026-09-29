from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='doctorweeklyavailability',
            name='default_duration_minutes',
            field=models.IntegerField(default=30),
        ),
        migrations.AddField(
            model_name='doctorweeklyavailability',
            name='buffer_minutes',
            field=models.IntegerField(default=0),
        ),
    ]
