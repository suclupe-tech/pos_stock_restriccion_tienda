from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén asignado")

    pos_config_id = fields.Many2one("pos.config", string="Punto de Venta asignado")
