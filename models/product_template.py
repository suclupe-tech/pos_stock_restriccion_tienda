from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields += ["qty_available", "virtual_available"]
        return fields