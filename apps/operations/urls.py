from django.urls import path
from . import views, advanced_views
urlpatterns = [
    path('suite/specialties/<slug:slug>/<int:pk>/', advanced_views.specialty_detail, name='suite-specialty-detail'),
    path('suite/specialty-follow-up/', advanced_views.specialty_follow_up, name='suite-specialty-follow-up'),
    path('suite/cards/<int:pk>/', advanced_views.identity_card, name='suite-card'),
    path('suite/barcodes/<slug:kind>/<int:pk>/', advanced_views.barcode, name='suite-barcode'),
    path('suite/insurance/prepare/', advanced_views.prepare_insurance, name='suite-prepare-claim'),
    path('suite/claims/<int:pk>/export/', advanced_views.claim_export, name='suite-claim-export'),
    path('suite/collections/<int:pk>/provider/<slug:operation>/', advanced_views.collection_provider, name='suite-provider'),
    path('suite/medication-round/', advanced_views.medication_round, name='suite-medication-round'),
    path('suite/reorder-report/', advanced_views.reorder_report, name='suite-reorder'),
    path('suite/stock/', views.stock_workspace, name='suite-stock'),
    path('suite/', views.workspace, name='suite-home'),
    path('suite/patient/<int:pk>/', views.patient_summary, name='suite-patient'),
    path('suite/results/<int:pk>/download/', views.result_download, name='suite-download'),
    path('suite/grants/<int:pk>/revoke/', views.revoke_grant, name='suite-revoke'),
    path('suite/<slug:slug>/', views.collection, name='suite-collection'),
    path('suite/<slug:slug>/<int:pk>/<slug:operation>/', views.action, name='suite-action'),
]
