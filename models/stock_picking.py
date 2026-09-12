from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # ============================================================
    # RELACIÓN CON EL NUEVO FLUJO DE TRANSFERENCIAS TRF
    #
    # Estos campos permiten distinguir los movimientos internos
    # creados automáticamente por dt.store.transfer de una
    # transferencia interna creada manualmente en Odoo.
    #
    # Esto permitirá posteriormente ocultar estos movimientos
    # técnicos de las vistas y exportaciones operativas, pero
    # conservarlos para auditoría y control de stock.
    # ============================================================

    is_store_transfer_technical = fields.Boolean(
        string="Movimiento técnico TRF",
        default=False,
        copy=False,
        index=True,
    )

    store_transfer_id = fields.Many2one(
        "dt.store.transfer",
        string="Transferencia TRF",
        copy=False,
        index=True,
        ondelete="set null",
    )

    # ============================================================
    # PROTECCIÓN DEL HISTORIAL ANTIGUO DE TRANSFERENCIAS
    #
    # Los traslados internos antiguos continúan almacenados en
    # stock.picking y deben conservarse únicamente para consulta.
    #
    # Para usuarios restringidos:
    # - no se pueden crear nuevos traslados internos manuales;
    # - no se pueden editar los traslados internos antiguos;
    # - no se pueden eliminar;
    # - no se pueden validar.
    #
    # IMPORTANTE:
    # Los movimientos técnicos creados por TRF/DEV sí están
    # permitidos porque llevan:
    #
    # is_store_transfer_technical = True
    # ============================================================

    def _is_restricted_store_user(self):
        """Indica si el usuario utiliza la restricción por tienda."""
        user = self.env.user

        return user.has_group(
            "pos_stock_restriccion_tienda.group_tienda_restringida"
        ) and not user.has_group("base.group_system")

    def _is_legacy_internal_picking(self):
        """
        Devuelve los traslados internos normales de Odoo.

        No incluye los movimientos técnicos utilizados internamente
        por los documentos TRF/DEV.
        """
        return self.filtered(
            lambda picking: picking.picking_type_id.code == "internal"
            and not picking.is_store_transfer_technical
        )

    # ============================================================
    # IMPEDIR CREAR NUEVOS TRASLADOS INTERNOS ANTIGUOS
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):

        if self._is_restricted_store_user():

            for vals in vals_list:

                # Los movimientos técnicos TRF/DEV deben poder crearse.
                if vals.get("is_store_transfer_technical"):
                    continue

                picking_type_id = vals.get("picking_type_id")

                if not picking_type_id:
                    continue

                picking_type = self.env["stock.picking.type"].browse(picking_type_id)

                if picking_type.code == "internal":
                    raise UserError(
                        "Las transferencias internas nuevas deben "
                        "realizarse desde el flujo de Transferencias TRF."
                    )

        return super().create(vals_list)

    # ============================================================
    # IMPEDIR EDICIÓN DEL HISTORIAL ANTIGUO
    # ============================================================
    def write(self, vals):

        if self._is_restricted_store_user():

            legacy_pickings = self._is_legacy_internal_picking()

            if legacy_pickings:
                raise UserError(
                    "Las transferencias anteriores son de solo lectura. "
                    "No pueden modificarse."
                )

        return super().write(vals)

    # ============================================================
    # IMPEDIR ELIMINACIÓN DEL HISTORIAL ANTIGUO
    # ============================================================
    def unlink(self):

        if self._is_restricted_store_user():

            legacy_pickings = self._is_legacy_internal_picking()

            if legacy_pickings:
                raise UserError(
                    "Las transferencias anteriores forman parte del "
                    "historial y no pueden eliminarse."
                )

        return super().unlink()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        user = self.env.user

        # No modificar el comportamiento normal de administradores
        # u otros usuarios que no tengan restricción por tienda.
        if not user.has_group("pos_stock_restriccion_tienda.group_tienda_restringida"):
            return res

        # Utilizar únicamente la configuración de nuestro módulo.
        warehouse = user.warehouse_id

        if not warehouse and user.allowed_warehouse_ids:
            warehouse = user.allowed_warehouse_ids[:1]

        # Si el usuario no tiene almacén configurado,
        # no seleccionar arbitrariamente otro almacén.
        if not warehouse:
            return res

        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", warehouse.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if picking_type:
            res["picking_type_id"] = picking_type.id

            if picking_type.default_location_src_id:
                res["location_id"] = picking_type.default_location_src_id.id

            if picking_type.default_location_dest_id:
                res["location_dest_id"] = picking_type.default_location_dest_id.id

        return res

    @api.onchange("picking_type_id")
    def _onchange_picking_type_tienda(self):
        if not self.picking_type_id:
            return

        if self.picking_type_id.default_location_src_id:
            self.location_id = self.picking_type_id.default_location_src_id

        if self.env.user.has_group(
            "pos_stock_restriccion_tienda.group_tienda_restringida"
        ):
            self.location_dest_id = False
        elif self.picking_type_id.default_location_dest_id:
            self.location_dest_id = self.picking_type_id.default_location_dest_id

    @api.model
    def get_action_picking_tree_internal(self):
        if self.env.user.has_group(
            "pos_stock_restriccion_tienda.group_tienda_restringida"
        ):
            return self.env.user.action_transferencias_mi_tienda()

        return super().get_action_picking_tree_internal()

    def button_validate(self):
        for picking in self:

            # Aplicar esta validación solamente a usuarios de tienda restringidos
            if not self.env.user.has_group(
                "pos_stock_restriccion_tienda.group_tienda_restringida"
            ):
                continue

            # Solo controlar transferencias internas
            if picking.picking_type_id.code != "internal":
                continue

            # --------------------------------------------------------
            # LOS TRASLADOS INTERNOS ANTIGUOS SON SOLO LECTURA
            #
            # Los movimientos técnicos TRF/DEV sí continúan porque
            # necesitan validarse automáticamente para mover stock.
            # --------------------------------------------------------
            if not picking.is_store_transfer_technical:
                raise UserError(
                    "Esta transferencia pertenece al historial anterior "
                    "y es de solo lectura."
                )

            warehouse_origen = picking.location_id.warehouse_id
            warehouse_destino = picking.location_dest_id.warehouse_id

            # Evitar transferencias hacia el mismo almacén
            if (
                warehouse_origen
                and warehouse_destino
                and warehouse_origen == warehouse_destino
            ):
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Revisa la tienda de destino",
                        "message": (
                            "El origen y el destino pertenecen al almacén "
                            f"{warehouse_origen.name}. "
                            "Selecciona la tienda de destino correcta antes de validar."
                        ),
                        "type": "warning",
                        "sticky": False,
                    },
                }

        return super().button_validate()
