from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    visible_tienda = fields.Boolean(
        string="Visible para usuario de tienda",
        default=False,
        help="Si está marcado, este tipo de operación aparecerá para usuarios de tienda restringidos.",
    )
