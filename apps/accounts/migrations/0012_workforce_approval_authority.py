from decimal import Decimal

from django.db import migrations, models


FINANCIAL = ['purchase', 'budget', 'expense', 'settlement', 'credit', 'refund', 'return', 'price']
WORKFORCE = ['attendance_review', 'leave_review', 'cover_review', 'roster_publish']


class Migration(migrations.Migration):
    dependencies = [('accounts', '0011_approvalgrant_approvalpolicy')]

    operations = [
        migrations.AlterField(
            model_name='approvalgrant', name='operation',
            field=models.CharField(max_length=20, choices=[
                ('purchase', 'Purchase orders'), ('budget', 'Operating budgets'),
                ('expense', 'Operating expenses'), ('settlement', 'Expense reconciliation'),
                ('credit', 'Invoice credits'), ('refund', 'Cash refund authorization'),
                ('return', 'Medicine returns'), ('price', 'Basket price changes'),
                ('attendance_review', 'Attendance review'), ('leave_review', 'Leave review'),
                ('cover_review', 'Cover and swap review'), ('roster_publish', 'Roster publication'),
            ]),
        ),
        migrations.AlterField(
            model_name='approvalgrant', name='maximum',
            field=models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name='approvalgrant',
            constraint=models.CheckConstraint(
                condition=(models.Q(operation__in=FINANCIAL, maximum__isnull=False, maximum__gte=0, maximum__lte=Decimal('999999999999.99'))
                           | models.Q(operation__in=WORKFORCE, maximum__isnull=True)),
                name='approval_grant_operation_limit',
            ),
        ),
    ]
