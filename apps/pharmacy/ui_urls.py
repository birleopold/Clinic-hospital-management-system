from django.urls import path
from . import ui_views, checkout_views

urlpatterns = [
    path('pharmacy/catalog/', checkout_views.catalog, name='pharmacy-catalog'),
    path('pharmacy/catalog/<int:pk>/', checkout_views.catalog_detail, name='pharmacy-catalog-detail'),
    path('pharmacy/policy/', checkout_views.policy, name='pharmacy-policy'),
    path('pharmacy/baskets/', checkout_views.baskets, name='pharmacy-baskets'),
    path('pharmacy/baskets/patients/', checkout_views.patient_lookup, name='pharmacy-basket-patients'),
    path('pharmacy/baskets/<int:pk>/', checkout_views.basket_detail, name='pharmacy-basket'),
    path('pharmacy/baskets/<int:pk>/action/', checkout_views.basket_action, name='pharmacy-basket-action'),
    path('pharmacy/baskets/<int:pk>/labels/', checkout_views.labels, name='pharmacy-basket-labels'),
    path('pharmacy', ui_views.pharmacy_board_view, name='pharmacy-board'),
    path('pharmacy/dispense', ui_views.dispense_create_view, name='pharmacy-dispense-create'),
    path('pharmacy/rx/<int:rx_id>', ui_views.rx_detail_view, name='rx-detail'),
    path('pharmacy/rx/<int:rx_id>/items/add', ui_views.rx_item_add_view, name='rx-item-add'),
    path('pharmacy/rx/item/<int:item_id>/delete', ui_views.rx_item_delete_view, name='rx-item-delete'),
    path('pharmacy/dispense/<int:dispense_id>/print', ui_views.dispense_print_view, name='pharmacy-dispense-print'),
    # Backorders UI
    path('pharmacy/backorders', ui_views.backorders_list_view, name='pharmacy-backorders'),
    path('pharmacy/backorders/<int:bo_id>', ui_views.backorder_detail_view, name='pharmacy-backorder-detail'),
    path('pharmacy/backorders/<int:bo_id>/fulfill', ui_views.backorder_fulfill_view, name='pharmacy-backorder-fulfill'),
    path('pharmacy/backorders/<int:bo_id>/close', ui_views.backorder_close_view, name='pharmacy-backorder-close'),
]
