{
    "name": "Restriccion por Tienda POS y Almacen",
    "version": "19.0.1.0.0",
    "summary": "Restringe usuarios a su almacen y punto de venta asignado",
    "author": "Detalles Textiles",
    "category": "Inventory/Point of Sale",
    "depends": ["base", "stock", "point_of_sale"],
    "data": [
        "security/security_groups.xml",
        "security/security_rules.xml",
        "security/ir.model.access.csv",
        "views/res_users_views.xml",
        "views/stock_quant_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
