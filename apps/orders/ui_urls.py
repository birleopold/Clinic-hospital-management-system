from django.urls import path
from . import ui_views

urlpatterns = [
    path('labs', ui_views.lab_worklist_view, name='labs-worklist'),
    path('labs/submit', ui_views.lab_submit_result_view, name='labs-submit-result'),
    path('orders/<int:order_id>/cancel', ui_views.cancel_order_ui_view, name='order-cancel'),
]
