from django.urls import path
from .views import DailyRevenueView, PatientVolumesView, ServiceMixView, RawInvoicesView, RawPaymentsView

urlpatterns = [
    path('reports/daily-revenue', DailyRevenueView.as_view(), name='daily-revenue'),
    path('reports/patient-volumes', PatientVolumesView.as_view(), name='patient-volumes'),
    path('reports/service-mix', ServiceMixView.as_view(), name='service-mix'),
    path('reports/raw-invoices', RawInvoicesView.as_view(), name='raw-invoices'),
    path('reports/raw-payments', RawPaymentsView.as_view(), name='raw-payments'),
]
