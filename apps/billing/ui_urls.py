from django.urls import path
from . import ui_views

urlpatterns = [
    path('cashier', ui_views.cashier_view, name='cashier'),
    path('cashier/invoice/<int:invoice_id>/print', ui_views.invoice_print_view, name='invoice-print'),
    path('cashier/receipt/<int:payment_id>/print', ui_views.receipt_print_view, name='receipt-print'),
    path('cashier/session/open', ui_views.cash_session_open_view, name='cash-session-open'),
    path('cashier/session/close', ui_views.cash_session_close_view, name='cash-session-close'),
    path('cashier/session/report', ui_views.cash_session_report_view, name='cash-session-report'),
    path('cashier/session/<int:session_id>/report', ui_views.cash_session_report_view, name='cash-session-report-id'),
    path('cashier/cashbook', ui_views.cashbook_view, name='cashbook'),
    path('billing/settings', ui_views.settings_view, name='billing-settings'),
]
