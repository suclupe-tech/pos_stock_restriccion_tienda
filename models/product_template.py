from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)

        # Evitar duplicados en la lista de campos
        for field_name in ["qty_available", "virtual_available"]:
            if field_name not in fields:
                fields.append(field_name)

        return fields
