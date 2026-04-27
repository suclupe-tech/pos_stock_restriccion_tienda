from odoo import models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):

        for picking in self:

            # solo transferencias internas
            if picking.picking_type_code != "internal":
                continue

            user_warehouse = self.env.user.warehouse_id

            if not user_warehouse:
                continue

            destino = picking.location_dest_id.warehouse_id

            if destino and destino.id != user_warehouse.id:
                raise UserError(
                    "Solo el almacén destino puede validar esta transferencia."
                )

        return super().button_validate()
