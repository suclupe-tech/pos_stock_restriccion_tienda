from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class StoreTransfer(models.Model):
    _name = "dt.store.transfer"
    _description = "Transferencia entre Tiendas"
    _order = "id desc"

    def _default_source_warehouse(self):
        user = self.env.user

        if user.warehouse_id:
            return user.warehouse_id

        if user.allowed_warehouse_ids:
            return user.allowed_warehouse_ids[:1]

        return False

    name = fields.Char(
        string="N.º Transferencia",
        default="Nuevo",
        readonly=True,
        copy=False,
        required=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )

    # ============================================================
    # DATOS GENERALES DEL TRASLADO
    # Campos similares a los que ya utiliza Odoo en sus
    # transferencias internas.
    # ============================================================

    # Contacto opcional relacionado con el traslado.
    # Puede dejarse vacío si no se necesita.
    partner_id = fields.Many2one(
        "res.partner",
        string="Contacto",
    )

    # Fecha prevista para realizar el envío.
    scheduled_date = fields.Datetime(
        string="Fecha programada",
        required=True,
        default=fields.Datetime.now,
    )

    # Referencia externa o documento relacionado.
    # Ejemplo: guía, pedido, orden interna, etc.
    origin_reference = fields.Char(
        string="Documento origen",
    )

    # Nota libre para alguna indicación adicional.
    note = fields.Text(
        string="Nota",
    )

    source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Origen",
        required=True,
        default=_default_source_warehouse,
    )

    # ============================================================
    # DESTINO DE LA TRANSFERENCIA
    # El usuario selecciona una ubicación de destino permitida.
    # Esto permite enviar a otras tiendas sin quitar las
    # restricciones de seguridad existentes sobre stock.warehouse.
    # ============================================================
    destination_location_id = fields.Many2one(
        "stock.location",
        string="Destino",
        required=True,
    )

    # ============================================================
    # DESTINOS PERMITIDOS PARA EL USUARIO ACTUAL
    # Utiliza la configuración que ya existe en res.users.
    # Ejemplo: Huánuco podrá seleccionar Planta, Gamarra, Monarca,
    # pero no su propio almacén.
    # ============================================================
    allowed_destination_location_ids = fields.Many2many(
        "stock.location",
        string="Destinos permitidos",
        compute="_compute_allowed_destination_locations",
    )

    @api.depends_context("uid")
    def _compute_allowed_destination_locations(self):
        # destination_location_ids ya es calculado por nuestro módulo
        # según los almacenes permitidos del usuario.
        allowed_locations = self.env.user.destination_location_ids

        for transfer in self:
            transfer.allowed_destination_location_ids = allowed_locations

    # ============================================================
    # ALMACÉN DESTINO
    # Se obtiene automáticamente desde la ubicación seleccionada.
    # Es un dato técnico; la vendedora no necesita seleccionarlo.
    # ============================================================
    destination_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Almacén destino",
        compute="_compute_destination_warehouse",
        store=True,
        readonly=True,
    )

    @api.depends("destination_location_id")
    def _compute_destination_warehouse(self):
        for transfer in self:
            transfer.destination_warehouse_id = (
                transfer.destination_location_id.warehouse_id
                if transfer.destination_location_id
                else False
            )

    # ============================================================
    # ORIGEN VISIBLE DE LA TRANSFERENCIA
    # Se obtiene automáticamente del almacén asignado al usuario.
    # ============================================================
    source_location_id = fields.Many2one(
        "stock.location",
        string="Origen",
        related="source_warehouse_id.lot_stock_id",
        store=True,
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("waiting", "Por recibir"),
            ("observed", "Observada"),
            ("received", "Recibida"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
    )

    # ============================================================
    # ROL DEL USUARIO EN LA TRANSFERENCIA
    #
    # Permite saber si el usuario conectado pertenece al almacén
    # origen o al almacén destino.
    #
    # Se utilizará para controlar botones y campos de la pantalla.
    # ============================================================
    is_source_user = fields.Boolean(
        string="Es usuario origen",
        compute="_compute_transfer_user_role",
    )

    is_destination_user = fields.Boolean(
        string="Es usuario destino",
        compute="_compute_transfer_user_role",
    )

    @api.depends("source_warehouse_id", "destination_warehouse_id")
    @api.depends_context("uid")
    def _compute_transfer_user_role(self):
        user = self.env.user

        # Almacenes que tiene permitidos el usuario conectado.
        allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

        for transfer in self:
            transfer.is_source_user = transfer.source_warehouse_id in allowed_warehouses

            transfer.is_destination_user = (
                transfer.destination_warehouse_id in allowed_warehouses
            )

    line_ids = fields.One2many(
        "dt.store.transfer.line",
        "transfer_id",
        string="Productos",
        copy=True,
    )

    sent_by_id = fields.Many2one(
        "res.users",
        string="Enviado por",
        readonly=True,
        copy=False,
    )

    sent_date = fields.Datetime(
        string="Fecha de envío",
        readonly=True,
        copy=False,
    )

    observed_by_id = fields.Many2one(
        "res.users",
        string="Observado por",
        readonly=True,
        copy=False,
    )

    observed_date = fields.Datetime(
        string="Fecha de observación",
        readonly=True,
        copy=False,
    )

    received_by_id = fields.Many2one(
        "res.users",
        string="Recibido por",
        readonly=True,
        copy=False,
    )

    received_date = fields.Datetime(
        string="Fecha de recepción",
        readonly=True,
        copy=False,
    )

    sent_picking_id = fields.Many2one(
        "stock.picking",
        string="Movimiento de salida",
        readonly=True,
        copy=False,
    )

    receipt_picking_id = fields.Many2one(
        "stock.picking",
        string="Movimiento de recepción",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # AUDITORÍA DE CORRECCIONES
    #
    # Guarda quién corrigió una transferencia observada,
    # cuándo se realizó la corrección y qué movimientos técnicos
    # se generaron para ajustar el stock que está en tránsito.
    # ============================================================

    corrected_by_id = fields.Many2one(
        "res.users",
        string="Corregido por",
        readonly=True,
        copy=False,
    )

    corrected_date = fields.Datetime(
        string="Fecha de corrección",
        readonly=True,
        copy=False,
    )

    correction_picking_ids = fields.Many2many(
        "stock.picking",
        string="Movimientos de corrección",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # NÚMERO AUTOMÁTICO DE TRANSFERENCIA
    # Al crear un documento genera TRF/000001, TRF/000002, etc.
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("dt.store.transfer") or "Nuevo"
                )

        return super().create(vals_list)

    # ============================================================
    # ENVIAR MERCADERÍA
    #
    # Valida el stock del almacén origen y mueve las prendas
    # únicamente hacia la ubicación técnica de tránsito.
    #
    # La mercadería todavía NO ingresa al almacén destino.
    # Después del envío, la transferencia queda "Por recibir".
    # ============================================================
    def action_send_transfer(self):
        self.ensure_one()

        # --------------------------------------------------------
        # 1. Solo una transferencia en Borrador puede enviarse.
        # --------------------------------------------------------
        if self.state != "draft":
            raise UserError(
                "Solo se pueden enviar transferencias que estén en Borrador."
            )

        # --------------------------------------------------------
        # 2. Validaciones básicas del documento.
        # --------------------------------------------------------
        if not self.source_warehouse_id or not self.source_location_id:
            raise UserError("No se pudo determinar el almacén de origen.")

        if not self.destination_location_id or not self.destination_warehouse_id:
            raise UserError("Debe seleccionar una ubicación de destino.")

        if self.source_warehouse_id == self.destination_warehouse_id:
            raise UserError(
                "El almacén de origen y el almacén de destino deben ser diferentes."
            )

        if not self.line_ids:
            raise UserError("Debe agregar al menos un producto a la transferencia.")

        # --------------------------------------------------------
        # 3. Seguridad:
        #    el usuario solo puede enviar desde uno de sus
        #    almacenes permitidos.
        # --------------------------------------------------------
        user = self.env.user
        allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

        if self.source_warehouse_id not in allowed_warehouses:
            raise UserError(
                "No tiene permiso para enviar mercadería desde este almacén."
            )

        # --------------------------------------------------------
        # 4. Obtener la ubicación de tránsito que ya posee Odoo.
        #    Ejemplo: "Traslado entre almacenes".
        # --------------------------------------------------------
        transit_location = self.company_id.internal_transit_location_id

        if not transit_location:
            raise UserError(
                "La empresa no tiene configurada una ubicación de tránsito."
            )

        # --------------------------------------------------------
        # 5. Buscar el tipo de operación de Traslado interno
        #    correspondiente al almacén origen.
        # --------------------------------------------------------
        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", self.source_warehouse_id.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if not picking_type:
            raise UserError(
                "No se encontró un tipo de operación de traslado interno "
                "para el almacén de origen."
            )

        # --------------------------------------------------------
        # 6. Validar cantidades y acumular por producto.
        #    Se acumulan para evitar que un mismo producto repetido
        #    en varias líneas pueda superar el stock disponible.
        # --------------------------------------------------------
        quantities_by_product = {}

        for line in self.line_ids:

            if line.qty_sent <= 0:
                raise UserError(
                    f"La cantidad del producto {line.product_id.display_name} "
                    "debe ser mayor que cero."
                )

            quantities_by_product.setdefault(line.product_id, 0.0)
            quantities_by_product[line.product_id] += line.qty_sent

        # --------------------------------------------------------
        # 7. COMPROBAR STOCK DISPONIBLE
        #
        # Primero validamos TODOS los productos antes de crear
        # cualquier movimiento de inventario.
        # --------------------------------------------------------
        Quant = self.env["stock.quant"]

        for product, requested_qty in quantities_by_product.items():

            available_qty = Quant._get_available_quantity(
                product,
                self.source_location_id,
            )

            if float_compare(
                available_qty,
                requested_qty,
                precision_rounding=product.uom_id.rounding,
            ) < 0:
                raise UserError(
                    f"Stock insuficiente para {product.display_name}.\n\n"
                    f"Disponible: {available_qty}\n"
                    f"Solicitado: {requested_qty}"
                )

        # ========================================================
        # 8. PREPARAR LOS PRODUCTOS DEL MOVIMIENTO DE SALIDA
        #
        # Una vez comprobado que existe stock suficiente para
        # todos los productos, construimos las líneas que Odoo
        # moverá desde Origen -> Tránsito.
        # ========================================================
        move_values = []

        for line in self.line_ids:

            move_values.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.qty_sent,
                        "product_uom": line.uom_id.id,
                        "location_id": self.source_location_id.id,
                        "location_dest_id": transit_location.id,
                    },
                )
            )

        # --------------------------------------------------------
        # 9. Crear el movimiento técnico de salida.
        #
        # Para la vendedora seguirá existiendo solamente TRF/xxxxx.
        # Este stock.picking queda relacionado internamente.
        # --------------------------------------------------------
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.source_location_id.id,
                "location_dest_id": transit_location.id,
                "partner_id": self.partner_id.id if self.partner_id else False,
                "scheduled_date": self.scheduled_date,
                "origin": self.name,
                "move_ids": move_values,
            }
        )

        # Confirmar y reservar la mercadería.
        picking.action_confirm()
        picking.action_assign()

        # Indicar que se está procesando exactamente la cantidad
        # declarada en nuestra transferencia.
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty

        # Validar la salida real del almacén origen.
        result = picking.button_validate()

        # Si Odoo solicita algún asistente adicional, no dejamos
        # nuestro documento en un estado inconsistente.
        if result is not True:
            raise UserError(
                "Odoo requiere una validación adicional para completar "
                "este movimiento. La transferencia no fue enviada."
            )

        # ============================================================
        # GUARDAR CANTIDADES DEL ENVÍO
        #
        # Conservamos la cantidad original para auditoría y también
        # registramos cuánto producto quedó físicamente en tránsito.
        # ============================================================
        for line in self.line_ids:
            line.original_qty_sent = line.qty_sent
            line.qty_in_transit = line.qty_sent

        # --------------------------------------------------------
        # 11. Registrar quién hizo el envío y cambiar el estado.
        # --------------------------------------------------------
        self.write(
            {
                "state": "waiting",
                "sent_by_id": self.env.user.id,
                "sent_date": fields.Datetime.now(),
                "sent_picking_id": picking.id,
            }
        )

        return True

    # ============================================================
    # CONFIRMAR RECEPCIÓN
    #
    # El almacén destino registra la cantidad recibida.
    #
    # - Si todas las cantidades coinciden, la mercadería pasa
    #   de tránsito al almacén destino.
    #
    # - Si existe alguna diferencia, NO se mueve el stock al
    #   destino y la transferencia queda OBSERVADA para que el
    #   almacén origen corrija primero la cantidad enviada.
    # ============================================================
    def action_confirm_receipt(self):
        self.ensure_one()

        # --------------------------------------------------------
        # VALIDAR ESTADO
        # Solo una transferencia "Por recibir" puede procesarse.
        # --------------------------------------------------------
        if self.state != "waiting":
            raise UserError(
                "Esta transferencia no se encuentra pendiente de recepción."
            )

        # --------------------------------------------------------
        # VALIDAR USUARIO
        # Solo el almacén destino puede registrar la recepción.
        # --------------------------------------------------------
        if not self.is_destination_user:
            raise UserError(
                "Solo el almacén de destino puede confirmar esta recepción."
            )

        if not self.line_ids:
            raise UserError("La transferencia no contiene productos.")

        # ========================================================
        # COMPROBAR DIFERENCIAS
        #
        # Comparamos lo que origen declaró como enviado contra
        # lo que destino contó físicamente.
        # ========================================================
        lines_with_difference = self.line_ids.filtered(
            lambda line: float_compare(
                line.qty_received,
                line.qty_sent,
                precision_rounding=line.uom_id.rounding,
            )
            != 0
        )

        # ========================================================
        # CASO 1: EXISTE DIFERENCIA
        #
        # No se recibe ningún producto todavía.
        # Todo permanece en tránsito hasta que origen corrija.
        # ========================================================
        if lines_with_difference:

            self.write(
                {
                    "state": "observed",
                    "observed_by_id": self.env.user.id,
                    "observed_date": fields.Datetime.now(),
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Diferencia en recepción",
                    "message": (
                        "La cantidad recibida no coincide con la cantidad "
                        "enviada. La transferencia quedó OBSERVADA. "
                        "No se ingresó mercadería al almacén destino."
                    ),
                    "type": "warning",
                    "sticky": True,
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",
                    },
                },
            }

        # ========================================================
        # CASO 2: RECEPCIÓN SIN DIFERENCIAS
        #
        # Recién cuando todas las cantidades coinciden se mueve
        # la mercadería desde tránsito hacia el almacén destino.
        # ========================================================
        transit_location = self.company_id.internal_transit_location_id

        if not transit_location:
            raise UserError("No se encontró la ubicación de tránsito de la empresa.")

        # --------------------------------------------------------
        # Buscar el tipo de traslado interno correspondiente
        # al almacén destino.
        # --------------------------------------------------------
        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", self.destination_warehouse_id.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if not picking_type:
            raise UserError(
                "No se encontró el tipo de operación de traslado interno "
                "del almacén destino."
            )

        # --------------------------------------------------------
        # Preparar los movimientos de cada producto.
        # --------------------------------------------------------
        move_values = []

        for line in self.line_ids:
            move_values.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.qty_received,
                        "product_uom": line.uom_id.id,
                        "location_id": transit_location.id,
                        "location_dest_id": self.destination_location_id.id,
                    },
                )
            )

        # ========================================================
        # CREAR RECEPCIÓN TÉCNICA
        #
        # La vendedora seguirá viendo solamente TRF/xxxxx.
        # Este stock.picking queda como movimiento técnico interno.
        # ========================================================
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": transit_location.id,
                "location_dest_id": self.destination_location_id.id,
                "partner_id": self.partner_id.id if self.partner_id else False,
                "scheduled_date": self.scheduled_date,
                "origin": self.name,
                "move_ids": move_values,
            }
        )

        # Confirmar y reservar la mercadería.
        picking.action_confirm()
        picking.action_assign()

        # Registrar exactamente las cantidades recibidas.
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty

        result = picking.button_validate()

        # Si Odoo solicita un asistente adicional, detenemos el flujo
        # para evitar dejar nuestra transferencia inconsistente.
        if result is not True:
            raise UserError(
                "Odoo requiere una validación adicional para completar "
                "la recepción. No se finalizó la transferencia."
            )

        # ========================================================
        # FINALIZAR RECEPCIÓN
        # El producto ya se encuentra en el almacén destino.
        # ========================================================
        self.write(
            {
                "state": "received",
                "received_by_id": self.env.user.id,
                "received_date": fields.Datetime.now(),
                "receipt_picking_id": picking.id,
            }
        )

        # --------------------------------------------------------
        # Mostrar confirmación y refrescar automáticamente la vista.
        # Al recargar desaparecerá el botón "Confirmar recepción".
        # --------------------------------------------------------
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Recepción confirmada",
                "message": (
                    "La mercadería fue recibida correctamente "
                    "y ya ingresó al stock del almacén destino."
                ),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }

    # ============================================================
    # CONFIRMAR CORRECCIÓN DE TRANSFERENCIA OBSERVADA
    #
    # El almacén origen corrige la cantidad enviada para que
    # coincida con lo que el almacén destino contó físicamente.
    #
    # Ejemplo:
    #   Cantidad actualmente en tránsito: 2
    #   Cantidad recibida por destino:    1
    #   Origen corrige enviada:           2 -> 1
    #
    # Resultado:
    #   1 unidad vuelve de Tránsito -> Origen
    #   La transferencia vuelve a "Por recibir".
    # ============================================================
    def action_confirm_correction(self):
        self.ensure_one()

        # --------------------------------------------------------
        # VALIDACIONES DE ESTADO Y USUARIO
        # --------------------------------------------------------
        if self.state != "observed":
            raise UserError("Solo se pueden corregir transferencias observadas.")

        if not self.is_source_user:
            raise UserError(
                "Solo el almacén de origen puede corregir esta transferencia."
            )

        # --------------------------------------------------------
        # La corrección solo puede confirmarse cuando todas las
        # cantidades enviadas ya coincidan con lo contado por
        # el almacén destino.
        # --------------------------------------------------------
        lines_pending = self.line_ids.filtered(
            lambda line: float_compare(
                line.qty_sent,
                line.qty_received,
                precision_rounding=line.uom_id.rounding,
            )
            != 0
        )

        if lines_pending:
            raise UserError(
                "Todavía existen productos cuya cantidad enviada "
                "no coincide con la cantidad recibida."
            )

        transit_location = self.company_id.internal_transit_location_id

        if not transit_location:
            raise UserError("No se encontró la ubicación de tránsito de la empresa.")

        # --------------------------------------------------------
        # Usamos el tipo de traslado interno correspondiente
        # al almacén origen.
        # --------------------------------------------------------
        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", self.source_warehouse_id.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if not picking_type:
            raise UserError(
                "No se encontró el tipo de traslado interno " "del almacén origen."
            )

        correction_pickings = self.env["stock.picking"]

        # ========================================================
        # PROCESAR LAS DIFERENCIAS DE STOCK
        # ========================================================
        for line in self.line_ids:

            comparison = float_compare(
                line.qty_sent,
                line.qty_in_transit,
                precision_rounding=line.uom_id.rounding,
            )

            # ----------------------------------------------------
            # CASO 1
            # Origen reduce la cantidad enviada.
            #
            # Ejemplo:
            # En tránsito: 2
            # Corregido:   1
            #
            # Se devuelve 1 unidad:
            # Tránsito -> Origen
            # ----------------------------------------------------
            if comparison < 0:
                qty_to_return = line.qty_in_transit - line.qty_sent

                picking = self.env["stock.picking"].create(
                    {
                        "picking_type_id": picking_type.id,
                        "location_id": transit_location.id,
                        "location_dest_id": self.source_location_id.id,
                        "origin": "%s - Corrección" % self.name,
                        "move_ids": [
                            (
                                0,
                                0,
                                {
                                    "product_id": line.product_id.id,
                                    "product_uom_qty": qty_to_return,
                                    "product_uom": line.uom_id.id,
                                    "location_id": transit_location.id,
                                    "location_dest_id": self.source_location_id.id,
                                },
                            )
                        ],
                    }
                )

                picking.action_confirm()
                picking.action_assign()

                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty

                result = picking.button_validate()

                if result is not True:
                    raise UserError(
                        "Odoo requiere una validación adicional para "
                        "completar la devolución de la diferencia."
                    )

                correction_pickings |= picking

            # ----------------------------------------------------
            # CASO 2
            # Origen aumenta la cantidad enviada.
            #
            # Ejemplo:
            # En tránsito: 10
            # Corregido:   11
            #
            # Se envía 1 unidad adicional:
            # Origen -> Tránsito
            # ----------------------------------------------------
            elif comparison > 0:
                qty_to_send = line.qty_sent - line.qty_in_transit

                available_qty = self.env["stock.quant"]._get_available_quantity(
                    line.product_id,
                    self.source_location_id,
                )

                if (
                    float_compare(
                        available_qty,
                        qty_to_send,
                        precision_rounding=line.uom_id.rounding,
                    )
                    < 0
                ):
                    raise UserError(
                        "No hay stock suficiente de %s para enviar "
                        "la diferencia de %.2f."
                        % (line.product_id.display_name, qty_to_send)
                    )

                picking = self.env["stock.picking"].create(
                    {
                        "picking_type_id": picking_type.id,
                        "location_id": self.source_location_id.id,
                        "location_dest_id": transit_location.id,
                        "origin": "%s - Corrección" % self.name,
                        "move_ids": [
                            (
                                0,
                                0,
                                {
                                    "product_id": line.product_id.id,
                                    "product_uom_qty": qty_to_send,
                                    "product_uom": line.uom_id.id,
                                    "location_id": self.source_location_id.id,
                                    "location_dest_id": transit_location.id,
                                },
                            )
                        ],
                    }
                )

                picking.action_confirm()
                picking.action_assign()

                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty

                result = picking.button_validate()

                if result is not True:
                    raise UserError(
                        "Odoo requiere una validación adicional para "
                        "completar el envío de la diferencia."
                    )

                correction_pickings |= picking

            # La cantidad técnica que queda en tránsito debe
            # coincidir con la nueva cantidad corregida.
            line.qty_in_transit = line.qty_sent

        # ========================================================
        # FINALIZAR LA CORRECCIÓN
        #
        # Conservamos la cantidad que destino ya contó y volvemos
        # a dejar la transferencia pendiente de recepción.
        # ========================================================
        values = {
            "state": "waiting",
            "corrected_by_id": self.env.user.id,
            "corrected_date": fields.Datetime.now(),
        }

        # Agregamos los movimientos de corrección al historial
        # sin borrar correcciones anteriores.
        if correction_pickings:
            values["correction_picking_ids"] = [
                (4, picking.id) for picking in correction_pickings
            ]

        self.write(values)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Transferencia corregida",
                "message": (
                    "La diferencia fue corregida y la transferencia "
                    "volvió a quedar pendiente de recepción."
                ),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }

    @api.constrains("source_warehouse_id", "destination_warehouse_id")
    def _check_different_warehouses(self):
        for transfer in self:
            if (
                transfer.source_warehouse_id
                and transfer.destination_warehouse_id
                and transfer.source_warehouse_id == transfer.destination_warehouse_id
            ):
                raise ValidationError(
                    _(
                        "El almacén de origen y el almacén de destino deben ser diferentes."
                    )
                )


class StoreTransferLine(models.Model):
    _name = "dt.store.transfer.line"
    _description = "Detalle de Transferencia entre Tiendas"
    _order = "id"

    transfer_id = fields.Many2one(
        "dt.store.transfer",
        string="Transferencia",
        required=True,
        ondelete="cascade",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
    )

    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad",
        related="product_id.uom_id",
        readonly=True,
    )

    qty_sent = fields.Float(
        string="Cantidad enviada",
        required=True,
        default=1.0,
    )

    original_qty_sent = fields.Float(
        string="Cantidad inicial",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # CANTIDAD QUE ACTUALMENTE ESTÁ EN TRÁNSITO
    #
    # Se utilizará para controlar correcciones cuando el destino
    # reporte que recibió más o menos de lo registrado inicialmente.
    # Es un dato técnico y no se mostrará a la vendedora.
    # ============================================================
    qty_in_transit = fields.Float(
        string="Cantidad en tránsito",
        readonly=True,
        copy=False,
    )

    qty_received = fields.Float(
        string="Cantidad recibida",
        copy=False,
    )

    difference_qty = fields.Float(
        string="Diferencia",
        compute="_compute_difference",
    )

    has_difference = fields.Boolean(
        string="Tiene diferencia",
        compute="_compute_difference",
    )

    # ============================================================
    # DIFERENCIA ENTRE ENVIADO Y RECIBIDO
    # Solo se evalúa cuando la transferencia ya fue enviada.
    # En Borrador todavía no existe una recepción que comparar.
    # ============================================================
    @api.depends("qty_sent", "qty_received", "transfer_id.state")
    def _compute_difference(self):
        for line in self:

            # Mientras la transferencia esté en borrador,
            # todavía no debemos considerar diferencias.
            if line.transfer_id.state == "draft":
                line.difference_qty = 0.0
                line.has_difference = False
                continue

            # Cuando la mercadería ya está por recibir,
            # comparamos lo enviado contra lo registrado en destino.
            line.difference_qty = line.qty_received - line.qty_sent
            line.has_difference = bool(line.difference_qty)

    @api.constrains("qty_sent", "qty_received")
    def _check_quantities(self):
        for line in self:
            if line.qty_sent < 0:
                raise ValidationError(_("La cantidad enviada no puede ser negativa."))

            if line.qty_received < 0:
                raise ValidationError(_("La cantidad recibida no puede ser negativa."))
