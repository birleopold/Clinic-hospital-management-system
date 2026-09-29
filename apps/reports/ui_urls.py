from django.urls import path
from . import ui_views

urlpatterns = [
    path('reports', ui_views.reports_dashboard_view, name='reports-dashboard'),
]
