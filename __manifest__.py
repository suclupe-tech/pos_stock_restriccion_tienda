{
    "name": "Restriccion por Tienda POS y Almacen",
    "version": "19.0.1.0.0",
    "summary": "Restringe usuarios a su almacen y punto de venta asignado",
    "author": "Detalles Textiles",
    "category": "Inventory/Point of Sale",
    "depends": ["base", "stock", "point_of_sale"],
    "assets": {
        "web.assets_backend": [
            "pos_stock_restriccion_tienda/static/src/backend/js/variant_distribution_action.js",
            "pos_stock_restriccion_tienda/static/src/backend/xml/variant_distribution_action.xml",
        ],
    },
    "data": [
        # permisos y reglas de seguridad
        "security/security_groups.xml",
        # Permisos de acceso del nuevo modelo de transferencias
        "security/ir.model.access.csv",
        "wizard/store_transfer_cancel_wizard_views.xml",
        "security/security_rules.xml",
        # numero automatico de transferencias entre tiendas
        "data/store_transfer_sequence.xml",
        "data/store_transfer_return_sequence.xml",
        # vistas
        "views/res_users_views.xml",
        "views/stock_quant_views.xml",
        "views/stock_picking_type_views.xml",
        "views/stock_picking_menu_views.xml",
        "views/store_transfer_views.xml",
        "views/store_transfer_return_views.xml",
        "views/stock_picking_technical_filter.xml",
        "views/stock_picking_legacy_history_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
