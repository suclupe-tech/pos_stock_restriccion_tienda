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

    destination_location_ids = fields.Many2many(
        "stock.location",
        string="Ubicaciones disponibles como destino",
        compute="_compute_destination_location_ids",
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

    @api.depends("warehouse_id", "allowed_warehouse_ids", "company_id")
    def _compute_destination_location_ids(self):
        Warehouse = self.env["stock.warehouse"].sudo()

        for user in self:
            own_warehouses = user.allowed_warehouse_ids or user.warehouse_id

            other_warehouses = Warehouse.search(
                [
                    ("company_id", "=", user.company_id.id),
                    ("id", "not in", own_warehouses.ids),
                ]
            )

            user.destination_location_ids = other_warehouses.mapped("lot_stock_id")

    def action_productos_mi_tienda(self):
        user = self.env.user
        warehouses = user.allowed_warehouse_ids or user.warehouse_id

        locations = self.env["stock.location"].search(
            [("warehouse_id", "in", warehouses.ids), ("usage", "=", "internal")]
        )

        domain = [
            ("quantity", ">", 0),
            ("location_id", "in", locations.ids),
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
        warehouses = user.allowed_warehouse_ids or user.warehouse_id

        locations = self.env["stock.location"].search(
            [("warehouse_id", "in", warehouses.ids), ("usage", "=", "internal")]
        )

        domain = [
            ("location_id", "in", locations.ids),
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
        self.ensure_one()
        user = self.env.user

        # 1. Obtener los almacenes permitidos (1 para vendedor, 3 para supervisor)
        warehouses = user.allowed_warehouse_ids or user.warehouse_id

        source_locations = self.env["stock.location"].search(
            [
                ("warehouse_id", "in", warehouses.ids),
                ("usage", "=", "internal"),
            ]
        )

        allowed_picking_types = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "in", warehouses.ids),
                ("code", "=", "internal"),
            ]
        )

        destination_locations = user.destination_location_ids

        # 2. Buscar el tipo de operación "internal" perteneciente al almacén predeterminado o permitidos
        picking_type = False
        if user.warehouse_id:
            picking_type = self.env["stock.picking.type"].search(
                [
                    ("warehouse_id", "=", user.warehouse_id.id),
                    ("code", "=", "internal"),
                ],
                limit=1,
            )

        if not picking_type and warehouses:
            picking_type = self.env["stock.picking.type"].search(
                [("warehouse_id", "in", warehouses.ids), ("code", "=", "internal")],
                limit=1,
            )

        # 3. Filtrar en el listado las transferencias pertenecientes a sus almacenes permitidos
        domain = [("picking_type_id.code", "=", "internal")]
        if warehouses:
            domain.append(("picking_type_id.warehouse_id", "in", warehouses.ids))

        return {
            "type": "ir.actions.act_window",
            "name": "Transferencias de Mi Tienda",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": domain,
            "context": {
                "search_default_internal": 1,
                "default_picking_type_id": picking_type.id if picking_type else False,
                "default_location_id": (
                    picking_type.default_location_src_id.id
                    if picking_type and picking_type.default_location_src_id
                    else False
                ),
                "default_location_dest_id": False,
                "restrict_store_transfer": True,
                "allowed_transfer_picking_type_ids": allowed_picking_types.ids,
                "allowed_transfer_source_location_ids": source_locations.ids,
                "allowed_transfer_destination_location_ids": destination_locations.ids,
            },
        }
