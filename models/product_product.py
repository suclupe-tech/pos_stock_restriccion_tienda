from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)

        domain.append(("qty_available", ">", 0))

        return domain
