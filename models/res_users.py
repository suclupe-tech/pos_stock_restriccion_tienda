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

    # ============================================================
    # TRASLADOS INTERNOS DE LA TIENDA
    #
    # Mantiene el mismo acceso que ya utiliza la vendedora desde
    # la tarjeta "Traslados internos" de Inventario.
    #
    # Para usuarios restringidos, en lugar de abrir el traslado
    # estándar de Odoo, abre nuestro nuevo flujo de transferencias
    # con doble validación.
    # ============================================================
    def action_transferencias_mi_tienda(self):
        self.ensure_one()

        user = self.env.user

        # Almacenes que pertenecen al usuario conectado.
        # Normalmente será uno para la vendedora.
        warehouses = user.allowed_warehouse_ids or user.warehouse_id

        # Almacén que se colocará automáticamente como origen.
        default_warehouse = user.warehouse_id

        if not default_warehouse and warehouses:
            default_warehouse = warehouses[:1]

        # --------------------------------------------------------
        # Abrir nuestro documento de transferencias.
        # El usuario seguirá entrando por "Traslados internos".
        # --------------------------------------------------------
        return {
            "type": "ir.actions.act_window",
            "name": "Traslados internos",
            "res_model": "dt.store.transfer",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],

            # Solo muestra transferencias donde uno de los
            # almacenes del usuario participa como origen o destino.
            "domain": [
                "|",
                ("source_warehouse_id", "in", warehouses.ids),
                ("destination_warehouse_id", "in", warehouses.ids),
            ],

            "context": {
                # El origen se coloca automáticamente según la tienda.
                "default_source_warehouse_id": (
                    default_warehouse.id if default_warehouse else False
                ),
            },
        }
