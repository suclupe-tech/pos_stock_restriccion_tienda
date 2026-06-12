from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén predeterminado")

    allowed_warehouse_ids = fields.Many2many(
        "stock.warehouse",
        "res_users_allowed_warehouse_rel",
        "user_id",
        "warehouse_id",
        string="Almacenes permitidos",
    )

    pos_config_id = fields.Many2one(
        "pos.config", string="Punto de Venta predeterminado"
    )

    allowed_pos_config_ids = fields.Many2many(
        "pos.config",
        "res_users_allowed_pos_config_rel",
        "user_id",
        "pos_config_id",
        string="Puntos de Venta permitidos",
    )

    restriccion_config_estado = fields.Char(
        string="Estado restricción tienda", compute="_compute_restriccion_config_estado"
    )

    restriccion_config_nivel = fields.Selection(
        [
            ("ok", "Correcta"),
            ("incompleto", "Incompleta"),
            ("sin_config", "Sin configuración"),
        ],
        string="Nivel restricción tienda",
        compute="_compute_restriccion_config_estado",
    )

    @api.onchange("warehouse_id")
    def _onchange_warehouse_id_add_allowed(self):
        for user in self:
            if (
                user.warehouse_id
                and user.warehouse_id not in user.allowed_warehouse_ids
            ):
                user.allowed_warehouse_ids = [(4, user.warehouse_id.id)]

    @api.onchange("pos_config_id")
    def _onchange_pos_config_id_add_allowed(self):
        for user in self:
            if (
                user.pos_config_id
                and user.pos_config_id not in user.allowed_pos_config_ids
            ):
                user.allowed_pos_config_ids = [(4, user.pos_config_id.id)]

    def action_productos_mi_tienda(self):
        user = self.env.user

        warehouses = user.allowed_warehouse_ids
        if not warehouses and user.warehouse_id:
            warehouses = user.warehouse_id

        location_ids = warehouses.mapped("lot_stock_id").ids

        domain = [
            ("quantity", ">", 0),
            ("location_id", "in", location_ids),
        ]

        return {
            "type": "ir.actions.act_window",
            "name": "Productos de mi tienda",
            "res_model": "stock.quant",
            "view_mode": "list,pivot,graph",
            "domain": domain,
            "context": {
                "search_default_internal_loc": 1,
            },
        }

    def action_revision_stock_tiendas(self):
        user = self.env.user

        warehouses = user.allowed_warehouse_ids
        if not warehouses and user.warehouse_id:
            warehouses = user.warehouse_id

        location_ids = warehouses.mapped("lot_stock_id").ids

        domain = [
            ("location_id", "in", location_ids),
        ]

        return {
            "type": "ir.actions.act_window",
            "name": "Revisión de stock de tiendas",
            "res_model": "stock.quant",
            "view_mode": "list,pivot,graph",
            "domain": domain,
            "context": {
                "search_default_internal_loc": 1,
            },
        }

    def _compute_restriccion_config_estado(self):
        for user in self:
            tiene_configuracion = (
                user.warehouse_id
                or user.allowed_warehouse_ids
                or user.pos_config_id
                or user.allowed_pos_config_ids
            )

            if not tiene_configuracion:
                user.restriccion_config_estado = "Sin configuración de restricción."
                user.restriccion_config_nivel = "sin_config"
                continue

            faltantes = []

            if not user.warehouse_id:
                faltantes.append("almacén predeterminado")

            if not user.allowed_warehouse_ids:
                faltantes.append("almacenes permitidos")

            if not user.pos_config_id:
                faltantes.append("POS predeterminado")

            if not user.allowed_pos_config_ids:
                faltantes.append("POS permitidos")

            if faltantes:
                user.restriccion_config_estado = "Falta configurar: " + ", ".join(
                    faltantes
                )
                user.restriccion_config_nivel = "incompleto"
            else:
                user.restriccion_config_estado = "Configuración correcta."
                user.restriccion_config_nivel = "ok"

    def action_transferencias_mi_tienda(self):
        user = self.env.user

        warehouses = user.allowed_warehouse_ids
        if not warehouses and user.warehouse_id:
            warehouses = user.warehouse_id

        location_view_ids = warehouses.mapped("view_location_id").ids

        domain = [
            ("picking_type_id.code", "=", "internal"),
            ("picking_type_id.visible_tienda", "=", True),
            "|",
            ("location_id", "child_of", location_view_ids),
            ("location_dest_id", "child_of", location_view_ids),
        ]

        return {
            "type": "ir.actions.act_window",
            "name": "Transferencias de mi tienda",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": domain,
            "context": {
                "search_default_internal": 1,
            },
        }
