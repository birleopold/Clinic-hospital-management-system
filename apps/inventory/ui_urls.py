from django.urls import path
from . import ui_views

urlpatterns = [
    path('inventory/stock', ui_views.stock_view, name='inventory-stock'),
    path('inventory/movements', ui_views.movements_view, name='inventory-movements'),
    path('inventory/items/new', ui_views.item_create_view, name='inventory-item-create'),
    path('inventory/items/<int:item_id>/edit', ui_views.item_edit_view, name='inventory-item-edit'),
    path('inventory/items/<int:item_id>/batch/new', ui_views.batch_create_view, name='inventory-batch-create'),
    path('inventory/items/<int:item_id>/adjust', ui_views.item_adjust_view, name='inventory-item-adjust'),
    # Procurement - Suppliers
    path('inventory/suppliers', ui_views.suppliers_list_view, name='inventory-suppliers'),
    path('inventory/suppliers/new', ui_views.supplier_create_view, name='inventory-supplier-create'),
    path('inventory/suppliers/<int:supplier_id>/edit', ui_views.supplier_edit_view, name='inventory-supplier-edit'),
    # Procurement - Purchase Orders
    path('inventory/po', ui_views.po_list_view, name='inventory-po-list'),
    path('inventory/po/new', ui_views.po_create_view, name='inventory-po-create'),
    path('inventory/po/<int:po_id>', ui_views.po_edit_view, name='inventory-po-edit'),
    path('inventory/po/<int:po_id>/line/<int:line_id>/update', ui_views.po_line_update_view, name='inventory-po-line-update'),
    path('inventory/po/<int:po_id>/line/<int:line_id>/delete', ui_views.po_line_delete_view, name='inventory-po-line-delete'),
    path('inventory/po/<int:po_id>/approve', ui_views.po_approve_view, name='inventory-po-approve'),
    path('inventory/po/<int:po_id>/close', ui_views.po_close_view, name='inventory-po-close'),
    path('inventory/po/<int:po_id>/cancel', ui_views.po_cancel_view, name='inventory-po-cancel'),
    # Procurement - GRN
    path('inventory/grn', ui_views.grn_list_view, name='inventory-grn-list'),
    path('inventory/grn/new', ui_views.grn_create_view, name='inventory-grn-create'),
    path('inventory/grn/<int:grn_id>', ui_views.grn_detail_view, name='inventory-grn-detail'),
    path('inventory/grn/<int:grn_id>/post', ui_views.grn_post_view, name='inventory-grn-post'),
    # Inventory import
    path('inventory/import', ui_views.inventory_import_view, name='inventory-import'),
    path('inventory/import/sample', ui_views.inventory_import_sample_view, name='inventory-import-sample'),
]
