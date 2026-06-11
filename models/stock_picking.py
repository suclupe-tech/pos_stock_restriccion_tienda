from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        user = self.env.user

        if not user.has_group("pos_stock_restriccion_tienda.group_tienda_restringida"):
            return res

        if not user.warehouse_id:
            return res

        if (
            user.allowed_warehouse_ids
            and user.warehouse_id not in user.allowed_warehouse_ids
        ):
            return res

        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", user.warehouse_id.id),
                ("code", "=", "internal"),
                ("visible_tienda", "=", True),
            ],
            limit=1,
        )

        if picking_type:
            res["picking_type_id"] = picking_type.id

        return res
