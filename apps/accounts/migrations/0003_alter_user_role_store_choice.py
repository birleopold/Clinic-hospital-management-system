# Expand User.role choices to include store (inventory UI).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_department_facility_staffprofile_department_facility'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'Admin'),
                    ('reception', 'Reception'),
                    ('nurse', 'Nurse'),
                    ('clinician', 'Clinician'),
                    ('lab', 'Lab'),
                    ('pharmacy', 'Pharmacy'),
                    ('cashier', 'Cashier'),
                    ('manager', 'Manager'),
                    ('store', 'Store / inventory'),
                ],
                default='reception',
                max_length=32,
            ),
        ),
    ]
