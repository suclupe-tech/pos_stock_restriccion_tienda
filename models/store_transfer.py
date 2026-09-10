from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
        # 7. Comprobar que realmente exista stock disponible
        #    en el almacén origen antes de permitir el envío.
        # --------------------------------------------------------
        Quant = self.env["stock.quant"]

        for product, requested_qty in quantities_by_product.items():

            available_qty = Quant._get_available_quantity(
                product,
                self.source_location_id,
            )

            if available_qty < requested_qty:
                raise UserError(
                    f"Stock insuficiente para {product.display_name}.\n\n"
                    f"Disponible: {available_qty}\n"
                    f"Solicitado: {requested_qty}"
                )

            # ============================================================
            # PREPARAR LOS PRODUCTOS DEL MOVIMIENTO DE SALIDA
            # Esta lista almacenará todas las prendas que se moverán
            # desde el almacén origen hacia la ubicación de tránsito.
            # ============================================================
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

        # --------------------------------------------------------
        # 10. Guardar la cantidad declarada originalmente.
        #
        # Será importante si posteriormente el destino reporta
        # que realmente recibió una cantidad diferente.
        # --------------------------------------------------------
        for line in self.line_ids:
            line.original_qty_sent = line.qty_sent

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
