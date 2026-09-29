from django.urls import path
from . import ui_views

urlpatterns = [
    path('ehr', ui_views.ehr_board_view, name='ehr-board'),
    path('ehr/encounter/start', ui_views.start_encounter_view, name='ehr-start-encounter'),
    path('ehr/encounter/<int:encounter_id>', ui_views.encounter_detail_view, name='ehr-encounter-detail'),
    path('ehr/encounter/<int:encounter_id>/vitals/add', ui_views.add_vital_view, name='ehr-add-vital'),
    path('ehr/encounter/<int:encounter_id>/diagnoses/add', ui_views.add_diagnosis_view, name='ehr-add-diagnosis'),
    path('ehr/encounter/<int:encounter_id>/close', ui_views.close_encounter_view, name='ehr-close-encounter'),
    path('ehr/encounter/<int:encounter_id>/rx/create', ui_views.create_rx_view, name='ehr-create-rx'),
    path('ehr/encounter/<int:encounter_id>/orders/create', ui_views.create_lab_order_view, name='ehr-create-order'),
]
