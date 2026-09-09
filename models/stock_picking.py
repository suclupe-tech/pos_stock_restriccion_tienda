from odoo import api, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

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
