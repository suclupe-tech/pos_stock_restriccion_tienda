from odoo import models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        for picking in self:

            if picking.picking_type_code != "internal":
                continue

            user_warehouse = self.env.user.warehouse_id

            if not user_warehouse:
                continue

            destino_permitido = picking.location_dest_id.id in self.env["stock.location"].search([
                ("id", "child_of", user_warehouse.view_location_id.id)
            ]).ids

            if not destino_permitido:
                raise UserError(
                    "Solo el almacén destino puede validar esta transferencia."
                )

        return super().button_validate()