from django.urls import path
from . import views
urlpatterns = [
    path('suite/stock/', views.stock_workspace, name='suite-stock'),
    path('suite/', views.workspace, name='suite-home'),
    path('suite/patient/<int:pk>/', views.patient_summary, name='suite-patient'),
    path('suite/results/<int:pk>/download/', views.result_download, name='suite-download'),
    path('suite/grants/<int:pk>/revoke/', views.revoke_grant, name='suite-revoke'),
    path('suite/<slug:slug>/', views.collection, name='suite-collection'),
    path('suite/<slug:slug>/<int:pk>/<slug:operation>/', views.action, name='suite-action'),
]
