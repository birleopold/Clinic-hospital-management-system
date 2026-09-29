from django.urls import path
from . import ui_views

urlpatterns = [
    path('patients', ui_views.patient_list_view, name='patients-list'),
    path('patients/new', ui_views.patient_create_view, name='patients-create'),
    path('patients/<int:patient_id>/edit', ui_views.patient_edit_view, name='patients-edit'),
]
