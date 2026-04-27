from odoo import models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    @classmethod
    def _process_order(cls, order, draft, existing_order):
        env = cls.env
        config_id = order.get("data", {}).get("config_id")
        lines = order.get("data", {}).get("lines", [])

        config = env["pos.config"].browse(config_id)
        warehouse = config.picking_type_id.warehouse_id
        location = warehouse.lot_stock_id

        for line in lines:
            line_data = line[2]
            product_id = line_data.get("product_id")
            qty = line_data.get("qty", 0)

            product = env["product.product"].browse(product_id)

            if product.type != "product":
                continue

            disponible = env["stock.quant"]._get_available_quantity(product, location)

            if qty > disponible:
                raise UserError(
                    "Stock insuficiente.\n\n"
                    "Producto: %s\n"
                    "Disponible en tienda: %s\n"
                    "Cantidad vendida: %s"
                    % (product.display_name, disponible, qty)
                )

        return super()._process_order(order, draft, existing_order)