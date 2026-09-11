from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class StoreTransferReturn(models.Model):
    _name = "dt.store.transfer.return"
    _description = "Devolución de Transferencia entre Tiendas"
    _order = "id desc"

    # ============================================================
    # IDENTIFICACIÓN DE LA DEVOLUCIÓN
    # Generará documentos DEV/000001, DEV/000002, etc.
    # ============================================================
    name = fields.Char(
        string="N.º Devolución",
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
    # TRANSFERENCIA ORIGINAL
    #
    # La devolución siempre nace de una transferencia TRF que
    # previamente fue recibida.
    # ============================================================
    original_transfer_id = fields.Many2one(
        "dt.store.transfer",
        string="Transferencia original",
        required=True,
        readonly=True,
        copy=False,
    )

    # ============================================================
    # ORIGEN Y DESTINO DE LA DEVOLUCIÓN
    #
    # Son inversos a la transferencia original.
    #
    # Ejemplo:
    # TRF: Huánuco -> WH
    # DEV: WH -> Huánuco
    # ============================================================
    source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Origen devolución",
        required=True,
        readonly=True,
    )

    destination_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Destino devolución",
        required=True,
        readonly=True,
    )

    source_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación origen",
        required=True,
        readonly=True,
    )

    destination_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación destino",
        required=True,
        readonly=True,
    )

    # ============================================================
    # MOTIVO
    #
    # Ejemplos:
    # - Compostura
    # - Producto fallado
    # - Producto equivocado
    # - Cambio de tienda
    # ============================================================
    reason = fields.Text(
        string="Motivo de devolución",
    )

    # ============================================================
    # ESTADO
    #
    # Usaremos el mismo concepto de doble validación que en TRF.
    # ============================================================
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("waiting", "Por recibir"),
            ("observed", "Observada"),
            ("received", "Recibida"),
            ("cancelled", "Anulada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
    )

    # ============================================================
    # PRODUCTOS A DEVOLVER
    # ============================================================
    line_ids = fields.One2many(
        "dt.store.transfer.return.line",
        "return_id",
        string="Productos",
        copy=True,
    )

    # ============================================================
    # USUARIO ORIGEN Y USUARIO DESTINO DE LA DEVOLUCIÓN
    #
    # Permite controlar quién puede enviar y quién puede recibir
    # la devolución.
    # ============================================================

    is_source_user = fields.Boolean(
        string="Es usuario origen devolución",
        compute="_compute_return_user_role",
    )

    is_destination_user = fields.Boolean(
        string="Es usuario destino devolución",
        compute="_compute_return_user_role",
    )

    @api.depends("source_warehouse_id", "destination_warehouse_id")
    @api.depends_context("uid")
    def _compute_return_user_role(self):
        user = self.env.user

        allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

        for return_doc in self:
            return_doc.is_source_user = (
                return_doc.source_warehouse_id in allowed_warehouses
            )

            return_doc.is_destination_user = (
                return_doc.destination_warehouse_id in allowed_warehouses
            )

    # ============================================================
    # AUDITORÍA DEL ENVÍO Y RECEPCIÓN DE LA DEVOLUCIÓN
    # ============================================================

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

    # ============================================================
    # MOVIMIENTOS TÉCNICOS DE INVENTARIO
    # ============================================================

    sent_picking_id = fields.Many2one(
        "stock.picking",
        string="Movimiento de salida devolución",
        readonly=True,
        copy=False,
    )

    receipt_picking_id = fields.Many2one(
        "stock.picking",
        string="Movimiento de recepción devolución",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # NUMERACIÓN AUTOMÁTICA
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("dt.store.transfer.return")
                    or "Nuevo"
                )

        return super().create(vals_list)

    # ============================================================
    # EVITAR DEVOLUCIONES ACTIVAS DUPLICADAS
    #
    # Una transferencia TRF solo puede tener una devolución activa
    # a la vez.
    #
    # Estados considerados activos:
    # - Borrador
    # - Por recibir
    # - Observada
    #
    # Una vez que la devolución queda Recibida o Anulada, se podrá
    # crear otra devolución si todavía quedan prendas disponibles.
    # ============================================================
    @api.constrains("original_transfer_id", "state")
    def _check_single_active_return(self):
        for record in self:

            if not record.original_transfer_id:
                continue

            if record.state not in ("draft", "waiting", "observed"):
                continue

            other_return = self.search(
                [
                    ("id", "!=", record.id),
                    (
                        "original_transfer_id",
                        "=",
                        record.original_transfer_id.id,
                    ),
                    (
                        "state",
                        "in",
                        ("draft", "waiting", "observed"),
                    ),
                ],
                limit=1,
            )

            if other_return:
                raise ValidationError(
                    _(
                        "La transferencia %s ya tiene una devolución "
                        "activa: %s.\n\n"
                        "Debe completar o anular esa devolución antes "
                        "de crear una nueva."
                    )
                    % (
                        record.original_transfer_id.name,
                        other_return.name,
                    )
                )

    # ============================================================
    # VALIDAR TRANSFERENCIA ORIGINAL
    #
    # Una devolución solo puede originarse desde un TRF que ya fue
    # recibido completamente por el almacén destino.
    # ============================================================
    @api.constrains("original_transfer_id")
    def _check_original_transfer_received(self):
        for record in self:

            if (
                record.original_transfer_id
                and record.original_transfer_id.state != "received"
            ):
                raise ValidationError(
                    _(
                        "Solo se pueden crear devoluciones de "
                        "transferencias que estén en estado Recibida."
                    )
                )

    # ============================================================
    # ENVIAR DEVOLUCIÓN
    #
    # Mueve únicamente las cantidades seleccionadas desde el
    # almacén que recibió originalmente la mercadería hacia la
    # ubicación técnica de tránsito.
    #
    # Ejemplo:
    # TRF original: HUANUCO -> WH
    # DEV:          WH -> Tránsito
    #
    # Todavía NO ingresa mercadería a Huánuco.
    # Después del envío queda en estado "Por recibir".
    # ============================================================
    def action_send_return(self):
        self.ensure_one()

        # --------------------------------------------------------
        # VALIDAR ESTADO
        # --------------------------------------------------------
        if self.state != "draft":
            raise UserError("Solo se pueden enviar devoluciones que estén en Borrador.")

        # --------------------------------------------------------
        # SOLO EL ALMACÉN QUE DEVUELVE PUEDE HACER EL ENVÍO
        # --------------------------------------------------------
        if not self.is_source_user:
            raise UserError(
                "Solo el almacén de origen de la devolución puede enviarla."
            )

        # --------------------------------------------------------
        # MOTIVO OBLIGATORIO
        # --------------------------------------------------------
        if not (self.reason or "").strip():
            raise UserError("Debe ingresar el motivo de la devolución.")

        if not self.line_ids:
            raise UserError("La devolución no contiene productos.")

        # ========================================================
        # VALIDAR CANTIDADES
        # ========================================================
        lines_to_return = self.line_ids.filtered(
            lambda line: float_compare(
                line.qty_to_return,
                0.0,
                precision_rounding=line.uom_id.rounding,
            )
            > 0
        )

        if not lines_to_return:
            raise UserError("Debe ingresar al menos una cantidad a devolver.")

        for line in lines_to_return:

            if (
                float_compare(
                    line.qty_to_return,
                    line.available_return_qty,
                    precision_rounding=line.uom_id.rounding,
                )
                > 0
            ):
                raise UserError(
                    "La cantidad a devolver de %s supera la cantidad "
                    "disponible para devolución." % line.product_id.display_name
                )

        # ========================================================
        # UBICACIÓN DE TRÁNSITO
        # ========================================================
        transit_location = self.company_id.internal_transit_location_id

        if not transit_location:
            raise UserError("No se encontró la ubicación de tránsito de la empresa.")

        # ========================================================
        # TIPO DE OPERACIÓN DEL ALMACÉN QUE DEVUELVE
        # ========================================================
        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", self.source_warehouse_id.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if not picking_type:
            raise UserError(
                "No se encontró el tipo de traslado interno "
                "del almacén origen de la devolución."
            )

        # ========================================================
        # VALIDAR STOCK ANTES DE CREAR MOVIMIENTOS
        #
        # Acumulamos por producto para evitar que varias líneas del
        # mismo producto puedan superar el stock disponible.
        # ========================================================
        quantities_by_product = {}

        for line in lines_to_return:
            quantities_by_product.setdefault(
                line.product_id,
                0.0,
            )
            quantities_by_product[line.product_id] += line.qty_to_return

        Quant = self.env["stock.quant"]

        for product, requested_qty in quantities_by_product.items():

            available_qty = Quant._get_available_quantity(
                product,
                self.source_location_id,
            )

            if (
                float_compare(
                    available_qty,
                    requested_qty,
                    precision_rounding=product.uom_id.rounding,
                )
                < 0
            ):
                raise UserError(
                    "Stock insuficiente para devolver %s.\n\n"
                    "Disponible: %.2f\n"
                    "Solicitado: %.2f"
                    % (
                        product.display_name,
                        available_qty,
                        requested_qty,
                    )
                )

        # ========================================================
        # PREPARAR PRODUCTOS
        # Origen devolución -> Tránsito
        # ========================================================
        move_values = []

        for line in lines_to_return:

            move_values.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.qty_to_return,
                        "product_uom": line.uom_id.id,
                        "location_id": self.source_location_id.id,
                        "location_dest_id": transit_location.id,
                    },
                )
            )

        # ========================================================
        # CREAR MOVIMIENTO TÉCNICO DE SALIDA
        #
        # También lo marcamos como movimiento técnico TRF para que
        # no aparezca mezclado en las vistas operativas.
        # ========================================================
        picking = self.env["stock.picking"].create(
            {
                "is_store_transfer_technical": True,
                # Se conserva el vínculo con el TRF original.
                "store_transfer_id": self.original_transfer_id.id,
                "picking_type_id": picking_type.id,
                "location_id": self.source_location_id.id,
                "location_dest_id": transit_location.id,
                "origin": self.name,
                "move_ids": move_values,
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
                "completar el envío de la devolución."
            )

        # ========================================================
        # GUARDAR CUÁNTO QUEDÓ EN TRÁNSITO
        # ========================================================
        for line in self.line_ids:

            if line in lines_to_return:
                line.qty_in_transit = line.qty_to_return
            else:
                line.qty_in_transit = 0.0

        # ========================================================
        # FINALIZAR ENVÍO
        # ========================================================
        self.write(
            {
                "state": "waiting",
                "sent_by_id": self.env.user.id,
                "sent_date": fields.Datetime.now(),
                "sent_picking_id": picking.id,
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Devolución enviada",
                "message": (
                    "La mercadería fue enviada y quedó pendiente "
                    "de recepción en el almacén destino."
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
    # CONFIRMAR RECEPCIÓN DE DEVOLUCIÓN
    #
    # El almacén destino registra cuánto recibió realmente.
    #
    # - Si coincide con lo enviado:
    #   Tránsito -> almacén destino
    #   DEV pasa a "Recibida".
    #
    # - Si existe diferencia:
    #   NO se ingresa stock todavía.
    #   DEV pasa a "Observada".
    # ============================================================
    def action_confirm_return_receipt(self):
        self.ensure_one()

        # --------------------------------------------------------
        # VALIDAR ESTADO
        # --------------------------------------------------------
        if self.state != "waiting":
            raise UserError("Esta devolución no se encuentra pendiente de recepción.")

        # --------------------------------------------------------
        # SOLO EL ALMACÉN DESTINO PUEDE RECIBIR
        # --------------------------------------------------------
        if not self.is_destination_user:
            raise UserError(
                "Solo el almacén destino puede confirmar "
                "la recepción de esta devolución."
            )

        # Solo consideramos productos realmente enviados.
        lines_to_receive = self.line_ids.filtered(
            lambda line: float_compare(
                line.qty_to_return,
                0.0,
                precision_rounding=line.uom_id.rounding,
            )
            > 0
        )

        if not lines_to_receive:
            raise UserError("La devolución no contiene cantidades para recibir.")

        # ========================================================
        # COMPROBAR DIFERENCIAS
        #
        # Comparamos:
        # cantidad enviada en devolución
        # contra cantidad contada por el almacén destino.
        # ========================================================
        lines_with_difference = lines_to_receive.filtered(
            lambda line: float_compare(
                line.qty_received,
                line.qty_to_return,
                precision_rounding=line.uom_id.rounding,
            )
            != 0
        )

        # ========================================================
        # CASO 1: EXISTE DIFERENCIA
        #
        # La mercadería permanece en tránsito.
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
                    "title": "Diferencia en devolución",
                    "message": (
                        "La cantidad recibida no coincide con la "
                        "cantidad enviada. La devolución quedó OBSERVADA. "
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
        # CASO 2: RECEPCIÓN CONFORME
        #
        # Todas las cantidades coinciden.
        # Tránsito -> almacén destino de la devolución.
        # ========================================================
        transit_location = self.company_id.internal_transit_location_id

        if not transit_location:
            raise UserError("No se encontró la ubicación de tránsito de la empresa.")

        # Tipo de traslado interno del almacén que recibe.
        picking_type = self.env["stock.picking.type"].search(
            [
                ("warehouse_id", "=", self.destination_warehouse_id.id),
                ("code", "=", "internal"),
            ],
            limit=1,
        )

        if not picking_type:
            raise UserError(
                "No se encontró el tipo de traslado interno "
                "del almacén destino de la devolución."
            )

        # ========================================================
        # PREPARAR PRODUCTOS
        # Tránsito -> Destino devolución
        # ========================================================
        move_values = []

        for line in lines_to_receive:

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
        # Se mantiene vinculada al TRF original y oculta de la
        # vista operativa igual que los demás movimientos técnicos.
        # ========================================================
        picking = self.env["stock.picking"].create(
            {
                "is_store_transfer_technical": True,
                "store_transfer_id": self.original_transfer_id.id,
                "picking_type_id": picking_type.id,
                "location_id": transit_location.id,
                "location_dest_id": self.destination_location_id.id,
                "origin": self.name,
                "move_ids": move_values,
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
                "completar la recepción de la devolución."
            )

        # Ya no queda mercadería de esta DEV en tránsito.
        for line in lines_to_receive:
            line.qty_in_transit = 0.0

        # ========================================================
        # FINALIZAR DEVOLUCIÓN
        # ========================================================
        self.write(
            {
                "state": "received",
                "received_by_id": self.env.user.id,
                "received_date": fields.Datetime.now(),
                "receipt_picking_id": picking.id,
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Devolución recibida",
                "message": (
                    "La devolución fue recibida correctamente "
                    "y la mercadería ingresó al almacén destino."
                ),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }


class StoreTransferReturnLine(models.Model):
    _name = "dt.store.transfer.return.line"
    _description = "Detalle de Devolución de Transferencia"
    _order = "id"

    return_id = fields.Many2one(
        "dt.store.transfer.return",
        string="Devolución",
        required=True,
        ondelete="cascade",
    )

    # Línea original del TRF.
    original_transfer_line_id = fields.Many2one(
        "dt.store.transfer.line",
        string="Línea original",
        required=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        related="original_transfer_line_id.product_id",
        store=True,
        readonly=True,
    )

    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad",
        related="original_transfer_line_id.uom_id",
        readonly=True,
    )

    # Cantidad que realmente recibió la tienda en el TRF original.
    original_received_qty = fields.Float(
        string="Cantidad recibida originalmente",
        related="original_transfer_line_id.qty_received",
        readonly=True,
    )

    # ============================================================
    # CONTROL DE CANTIDADES DEVUELTAS
    #
    # Permite saber:
    # - cuánto recibió originalmente la tienda;
    # - cuánto ya devolvió mediante devoluciones anteriores;
    # - cuánto todavía tiene disponible para devolver.
    #
    # Ejemplo:
    # Recibido originalmente: 10
    # Ya devuelto:             2
    # Disponible devolver:     8
    # ============================================================

    already_returned_qty = fields.Float(
        string="Ya devuelto",
        compute="_compute_return_quantities",
        readonly=True,
    )

    available_return_qty = fields.Float(
        string="Disponible para devolver",
        compute="_compute_return_quantities",
        readonly=True,
    )

    @api.depends(
        "original_transfer_line_id",
        "original_received_qty",
    )
    def _compute_return_quantities(self):
        ReturnLine = self.env["dt.store.transfer.return.line"]

        for line in self:

            if not line.original_transfer_line_id:
                line.already_returned_qty = 0.0
                line.available_return_qty = 0.0
                continue

            # ----------------------------------------------------
            # Solo contabilizamos devoluciones que ya terminaron.
            #
            # De esta forma una devolución recibida realmente
            # reduce la cantidad que podrá devolverse después.
            # ----------------------------------------------------
            domain = [
                (
                    "original_transfer_line_id",
                    "=",
                    line.original_transfer_line_id.id,
                ),
                ("return_id.state", "=", "received"),
            ]

            # Evitamos que la propia línea se sume a sí misma.
            if line.id:
                domain.append(("id", "!=", line.id))

            previous_lines = ReturnLine.search(domain)

            already_returned = sum(previous_lines.mapped("qty_received"))

            line.already_returned_qty = already_returned

            line.available_return_qty = max(
                line.original_received_qty - already_returned,
                0.0,
            )

    # Cantidad que el usuario decide devolver.
    qty_to_return = fields.Float(
        string="Cantidad a devolver",
        required=True,
        default=0.0,
    )

    # ============================================================
    # CANTIDAD QUE QUEDA TÉCNICAMENTE EN TRÁNSITO
    #
    # Se utilizará para controlar la recepción y posteriormente
    # las diferencias de una devolución observada.
    # ============================================================

    qty_in_transit = fields.Float(
        string="Cantidad en tránsito",
        readonly=True,
        copy=False,
    )

    # Más adelante aquí registraremos cuánto recibe realmente
    # el almacén que recibe la devolución.
    qty_received = fields.Float(
        string="Cantidad recibida",
        copy=False,
    )

    @api.constrains("qty_to_return")
    def _check_qty_to_return(self):
        for line in self:
            if line.qty_to_return < 0:
                raise ValidationError(
                    _("La cantidad a devolver no puede ser negativa.")
                )

            if line.qty_to_return > line.available_return_qty:
                raise ValidationError(
                    _(
                        "No puede devolver %.2f unidades de %s.\n\n"
                        "Recibido originalmente: %.2f\n"
                        "Ya devuelto: %.2f\n"
                        "Disponible para devolver: %.2f"
                    )
                    % (
                        line.qty_to_return,
                        line.product_id.display_name,
                        line.original_received_qty,
                        line.already_returned_qty,
                        line.available_return_qty,
                    )
                )
