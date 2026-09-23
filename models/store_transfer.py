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

    # ============================================================
    # DESTINO QUE REQUIERE DISTRIBUCIÓN POR VARIANTES
    #
    # Se activa cuando el almacén destino trabaja:
    # - Por variantes
    # - Mixto
    #
    # No se crea una dependencia obligatoria con dt_catalogo_comercial.
    # Si el campo product_control_mode no existe, se considera False.
    # ============================================================
    destination_allows_variant_distribution = fields.Boolean(
        string="Destino usa variantes",
        compute="_compute_destination_allows_variant_distribution",
    )

    destination_requires_reception_choice = fields.Boolean(
        string="Destino requiere elegir forma de recepción",
        compute="_compute_destination_allows_variant_distribution",
    )

    @api.depends("destination_warehouse_id")
    def _compute_destination_allows_variant_distribution(self):
        for transfer in self:

            # --------------------------------------------------------
            # Lectura técnica del almacén destino.
            #
            # El usuario origen puede seleccionar una ubicación destino
            # permitida aunque no tenga acceso administrativo al almacén.
            # sudo() se utiliza únicamente para consultar su configuración.
            # --------------------------------------------------------
            warehouse = transfer.destination_warehouse_id.sudo()

            mode = (
                warehouse.product_control_mode
                if warehouse and "product_control_mode" in warehouse._fields
                else "model"
            )

            # El destino permite distribución manual cuando trabaja
            # por variantes o en modo mixto.
            transfer.destination_allows_variant_distribution = mode in (
                "variant",
                "mixed",
            )

            # En modo mixto el receptor debe escoger cómo recibirá.
            transfer.destination_requires_reception_choice = mode == "mixed"

    # ============================================================
    # MODO DE RECEPCIÓN EN DESTINO
    #
    # En un almacén mixto como TDA DIGITAL, el receptor decide:
    #
    # - Por modelo:
    #   recibe la cantidad agrupada, sin matriz.
    #
    # - Por variantes:
    #   debe distribuir manualmente Color x Talla.
    #
    # Se deja vacío inicialmente para que el almacén destino
    # elija explícitamente al momento de recibir.
    # ============================================================
    reception_mode = fields.Selection(
        [
            ("model", "Por modelo"),
            ("variant", "Por variantes"),
        ],
        string="Forma de recepción",
        copy=False,
    )

    # ============================================================
    # MODO EFECTIVO DE RECEPCIÓN
    #
    # Determina cómo debe ingresar la mercadería al destino.
    #
    # MODEL:
    # Siempre recibe agrupado por modelo.
    #
    # VARIANT:
    # Siempre recibe mediante variantes.
    #
    # MIXED:
    # El almacén destino debe elegir explícitamente.
    # ============================================================
    def _get_effective_reception_mode(self):
        self.ensure_one()

        warehouse = self.destination_warehouse_id

        if not warehouse:
            raise UserError("No se pudo determinar el almacén de destino.")

        # Compatibilidad si dt_catalogo_comercial no estuviera instalado.
        if "product_control_mode" not in warehouse._fields:
            return "model"

        warehouse_mode = warehouse.product_control_mode

        if warehouse_mode == "model":
            return "model"

        if warehouse_mode == "variant":
            return "variant"

        if warehouse_mode == "mixed":
            if self.reception_mode not in ("model", "variant"):
                raise UserError(
                    "Debe indicar si la mercadería será recibida "
                    "Por modelo o Por variantes."
                )

            return self.reception_mode

        return "model"

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
            ("cancelled", "Anulada"),
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

    # ============================================================
    # CONTROL DE COMPROBACIÓN DE STOCK
    #
    # False -> debe aparecer "Comprobar stock"
    # True  -> debe aparecer "Enviar mercadería"
    # ============================================================
    stock_checked = fields.Boolean(
        string="Stock comprobado",
        default=False,
        readonly=True,
        copy=False,
    )

    # ============================================================
    # DISPONIBILIDAD GENERAL DE LA TRANSFERENCIA
    #
    # unchecked   -> todavía no se ha comprobado
    # available   -> todos los productos tienen stock
    # unavailable -> uno o más productos no tienen stock suficiente
    # ============================================================
    stock_availability_state = fields.Selection(
        [
            ("unchecked", "Sin comprobar"),
            ("available", "Disponible"),
            ("unavailable", "No disponible"),
        ],
        string="Disponibilidad del producto",
        default="unchecked",
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
    # AUDITORÍA DE ANULACIÓN
    #
    # Conserva el motivo, usuario y fecha de anulación.
    # Si la transferencia ya había salido del almacén, también
    # guardaremos el movimiento técnico utilizado para devolver
    # la mercadería en tránsito al almacén origen.
    # ============================================================

    cancel_reason = fields.Text(
        string="Motivo de anulación",
        readonly=True,
        copy=False,
    )

    cancelled_by_id = fields.Many2one(
        "res.users",
        string="Anulado por",
        readonly=True,
        copy=False,
    )

    cancelled_date = fields.Datetime(
        string="Fecha de anulación",
        readonly=True,
        copy=False,
    )

    cancellation_picking_id = fields.Many2one(
        "stock.picking",
        string="Movimiento de anulación",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # CREACIÓN SEGURA DE TRANSFERENCIAS TRF
    #
    # Los usuarios de tienda pueden crear TRF normalmente, pero:
    # - siempre deben nacer en Borrador;
    # - el origen debe pertenecer a sus almacenes permitidos;
    # - el destino debe ser una ubicación permitida;
    # - no pueden crear directamente estados, auditoría ni
    #   movimientos técnicos manipulados.
    #
    # Administradores/TI mantienen el comportamiento normal.
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):

        if self._is_restricted_store_user():

            user = self.env.user
            allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

            # Campos que únicamente deben ser generados o modificados
            # por los procesos internos del módulo.
            protected_fields = {
                "source_location_id",
                "destination_warehouse_id",
                "sent_by_id",
                "sent_date",
                "observed_by_id",
                "observed_date",
                "received_by_id",
                "received_date",
                "sent_picking_id",
                "receipt_picking_id",
                "corrected_by_id",
                "corrected_date",
                "correction_picking_ids",
                "cancel_reason",
                "cancelled_by_id",
                "cancelled_date",
                "cancellation_picking_id",
            }

            for vals in vals_list:

                # ------------------------------------------------
                # IMPEDIR CAMPOS TÉCNICOS EN LA CREACIÓN
                # ------------------------------------------------
                if set(vals) & protected_fields:
                    raise UserError(
                        "No puede establecer datos internos "
                        "al crear una transferencia."
                    )

                # ------------------------------------------------
                # EL DOCUMENTO SIEMPRE DEBE NACER EN BORRADOR
                # ------------------------------------------------
                if vals.get("state", "draft") != "draft":
                    raise UserError(
                        "Una transferencia nueva debe crearse " "en estado Borrador."
                    )

                # ------------------------------------------------
                # LA NUMERACIÓN LA GENERA EL SISTEMA
                # ------------------------------------------------
                if vals.get("name") not in (False, None, "Nuevo"):
                    raise UserError(
                        "El número de transferencia es generado "
                        "automáticamente por el sistema."
                    )

                # ------------------------------------------------
                # VALIDAR COMPAÑÍA
                # ------------------------------------------------
                if vals.get("company_id") and vals["company_id"] != self.env.company.id:
                    raise UserError(
                        "No puede crear la transferencia " "para otra compañía."
                    )

                # ------------------------------------------------
                # VALIDAR ALMACÉN ORIGEN
                #
                # Si no llega en vals utilizamos el almacén que
                # corresponde por defecto al usuario.
                # ------------------------------------------------
                source_warehouse_id = vals.get("source_warehouse_id")

                if not source_warehouse_id:
                    default_source = self._default_source_warehouse()
                    source_warehouse_id = default_source.id if default_source else False

                if not source_warehouse_id:
                    raise UserError("No tiene un almacén de origen configurado.")

                source_warehouse = self.env["stock.warehouse"].browse(
                    source_warehouse_id
                )

                if source_warehouse not in allowed_warehouses:
                    raise UserError(
                        "No puede crear una transferencia desde "
                        "un almacén que no tiene permitido."
                    )

                # ------------------------------------------------
                # VALIDAR UBICACIÓN DESTINO
                # ------------------------------------------------
                destination_location_id = vals.get("destination_location_id")

                if destination_location_id:

                    destination_location = self.env["stock.location"].browse(
                        destination_location_id
                    )

                    if destination_location not in user.destination_location_ids:
                        raise UserError(
                            "No puede seleccionar esa ubicación " "como destino."
                        )

        # ========================================================
        # GENERAR NÚMERO TRF
        # ========================================================
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("dt.store.transfer") or "Nuevo"
                )

        return super().create(vals_list)

    # ============================================================
    # SEGURIDAD DE ESCRITURA DEL DOCUMENTO TRF
    #
    # La interfaz ya utiliza readonly/invisible, pero estas reglas
    # protegen también el modelo desde servidor.
    #
    # Un usuario de tienda:
    # - puede editar datos operativos mientras el TRF está Borrador;
    # - después del envío no puede alterar el encabezado;
    # - nunca puede modificar manualmente estado, auditoría ni
    #   movimientos técnicos.
    #
    # Los procesos oficiales del módulo utilizan _write_internal()
    # para modificar esos campos de forma controlada.
    # ============================================================

    def _is_restricted_store_user(self):
        """Indica si debemos aplicar las restricciones de tienda."""
        user = self.env.user

        return user.has_group(
            "pos_stock_restriccion_tienda.group_tienda_restringida"
        ) and not user.has_group("base.group_system")

    def _write_internal(self, vals):
        """
        Escritura privada utilizada solamente por los procesos internos
        del TRF: envío, recepción, corrección y anulación.
        """
        return super(StoreTransfer, self).write(vals)

    def write(self, vals):

        fields_to_write = set(vals)

        # ========================================================
        # INVALIDAR COMPROBACIÓN DE STOCK
        #
        # Si cambia el almacén origen o la ubicación destino,
        # la comprobación anterior deja de ser válida.
        # ========================================================
        must_reset_stock = bool(
            {"source_warehouse_id", "destination_location_id"} & fields_to_write
        )

        draft_transfers = self.filtered(lambda transfer: transfer.state == "draft")

        # --------------------------------------------------------
        # Administradores/TI y usuarios no restringidos mantienen
        # el comportamiento normal de Odoo, pero también debemos
        # invalidar una comprobación anterior.
        # --------------------------------------------------------
        if not self._is_restricted_store_user():

            result = super().write(vals)

            if must_reset_stock and draft_transfers:
                draft_transfers._write_internal(
                    {
                        "stock_checked": False,
                        "stock_availability_state": "unchecked",
                    }
                )

                draft_transfers.mapped("line_ids")._write_internal(
                    {
                        "stock_availability_state": "unchecked",
                        "available_stock_qty": 0.0,
                    }
                )

            return result

        # --------------------------------------------------------
        # CAMPOS QUE NUNCA DEBE CAMBIAR MANUALMENTE UNA TIENDA
        # --------------------------------------------------------
        protected_fields = {
            "name",
            "company_id",
            "source_location_id",
            "destination_warehouse_id",
            "state",
            "sent_by_id",
            "sent_date",
            "observed_by_id",
            "observed_date",
            "received_by_id",
            "received_date",
            "sent_picking_id",
            "receipt_picking_id",
            "corrected_by_id",
            "corrected_date",
            "correction_picking_ids",
            "cancel_reason",
            "cancelled_by_id",
            "cancelled_date",
            "cancellation_picking_id",
        }

        forbidden_fields = fields_to_write & protected_fields

        if forbidden_fields:
            raise UserError(
                "No puede modificar directamente datos internos " "de la transferencia."
            )

        # --------------------------------------------------------
        # CAMPOS EDITABLES MIENTRAS ESTÁ EN BORRADOR
        # --------------------------------------------------------
        allowed_draft_fields = {
            "partner_id",
            "scheduled_date",
            "origin_reference",
            "note",
            "source_warehouse_id",
            "destination_location_id",
            "line_ids",
        }

        # Después del envío solo permitimos que Odoo procese cambios
        # en las líneas. La seguridad específica de esas líneas se
        # implementará en dt.store.transfer.line.
        allowed_after_send_fields = {
            "line_ids",
        }

        user = self.env.user
        allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

        # --------------------------------------------------------
        # VALIDAR CAMBIO DE ALMACÉN ORIGEN
        # --------------------------------------------------------
        if "source_warehouse_id" in vals:

            new_source = self.env["stock.warehouse"].browse(vals["source_warehouse_id"])

            if new_source not in allowed_warehouses:
                raise UserError(
                    "No puede seleccionar como origen un almacén "
                    "que no tiene permitido."
                )

        # --------------------------------------------------------
        # VALIDAR UBICACIÓN DESTINO
        # --------------------------------------------------------
        if "destination_location_id" in vals:

            new_destination = self.env["stock.location"].browse(
                vals["destination_location_id"]
            )

            if new_destination not in user.destination_location_ids:
                raise UserError("No puede seleccionar esa ubicación como destino.")

        # --------------------------------------------------------
        # VALIDAR SEGÚN EL ESTADO DE CADA TRF
        # --------------------------------------------------------
        for transfer in self:

            if transfer.state == "draft":

                if not transfer.is_source_user:
                    raise UserError(
                        "Solo el almacén origen puede modificar " "esta transferencia."
                    )

                invalid_fields = fields_to_write - allowed_draft_fields

                if invalid_fields:
                    raise UserError(
                        "No puede modificar esos datos de la transferencia."
                    )

            else:

                # Después del envío normalmente solo se modifican las líneas.
                allowed_fields = set(allowed_after_send_fields)

                # ========================================================
                # FORMA DE RECEPCIÓN
                #
                # Únicamente el almacén DESTINO puede decidir si recibirá
                # por modelo o por variantes mientras el TRF esté
                # pendiente de recepción.
                # ========================================================
                if transfer.state == "waiting" and transfer.is_destination_user:
                    allowed_fields.add("reception_mode")

                invalid_fields = fields_to_write - allowed_fields

                if invalid_fields:
                    raise UserError(
                        "La transferencia ya fue enviada y su información "
                        "general ya no puede modificarse."
                    )

        result = super().write(vals)

        # --------------------------------------------------------
        # Si cambió origen o destino mientras estaba en Borrador,
        # obligamos a realizar nuevamente la comprobación.
        # --------------------------------------------------------
        if must_reset_stock and draft_transfers:

            draft_transfers._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unchecked",
                }
            )

            draft_transfers.mapped("line_ids")._write_internal(
                {
                    "stock_availability_state": "unchecked",
                    "available_stock_qty": 0.0,
                }
            )

        return result

    # ============================================================
    # COMPROBAR STOCK
    #
    # Comprueba la disponibilidad sin mover mercadería.
    # El resultado queda visible en el formulario:
    #
    # - Disponible
    # - No disponible
    #
    # Si todo está disponible, habilita "Enviar mercadería".
    # ============================================================
    def action_check_stock(self):
        self.ensure_one()

        # --------------------------------------------------------
        # 1. Solo puede comprobarse en Borrador.
        # --------------------------------------------------------
        if self.state != "draft":
            raise UserError(
                "Solo se puede comprobar stock en una transferencia en Borrador."
            )

        # --------------------------------------------------------
        # 2. Validaciones básicas.
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
        # 3. Seguridad del almacén origen.
        # --------------------------------------------------------
        user = self.env.user
        allowed_warehouses = user.allowed_warehouse_ids or user.warehouse_id

        if self.source_warehouse_id not in allowed_warehouses:
            raise UserError(
                "No tiene permiso para enviar mercadería desde este almacén."
            )

        # --------------------------------------------------------
        # 4. Acumular cantidades por producto.
        #
        # Si el mismo producto está repetido en varias líneas,
        # se valida utilizando la cantidad total solicitada.
        # --------------------------------------------------------
        quantities_by_product = {}
        stock_product_by_line = {}

        for line in self.line_ids:

            if line.qty_sent <= 0:
                raise UserError(
                    f"La cantidad del producto {line.product_id.display_name} "
                    "debe ser mayor que cero."
                )

            # ----------------------------------------------------
            # Resolver qué product.product representa realmente
            # el stock en el almacén origen.
            #
            # Por modelo  -> SIN CLASIFICAR
            # Por variante -> variante seleccionada
            # ----------------------------------------------------
            stock_product = line._get_stock_product_for_warehouse(
                self.source_warehouse_id
            )

            stock_product_by_line[line.id] = stock_product

            quantities_by_product.setdefault(stock_product, 0.0)
            quantities_by_product[stock_product] += line.qty_sent
        # --------------------------------------------------------
        # 5. Comprobar disponibilidad.
        # --------------------------------------------------------
        Quant = self.env["stock.quant"]

        product_availability = {}
        product_available_qty = {}
        has_insufficient_stock = False

        for product, requested_qty in quantities_by_product.items():

            available_qty = Quant._get_available_quantity(
                product,
                self.source_location_id,
            )

            product_available_qty[product.id] = available_qty

            is_available = (
                float_compare(
                    available_qty,
                    requested_qty,
                    precision_rounding=product.uom_id.rounding,
                )
                >= 0
            )

            product_availability[product.id] = is_available

            if not is_available:
                has_insufficient_stock = True

        # --------------------------------------------------------
        # 6. Guardar disponibilidad de cada producto.
        # --------------------------------------------------------
        for line in self.line_ids:

            stock_product = stock_product_by_line[line.id]

            if product_availability.get(stock_product.id):
                line._write_internal(
                    {
                        "stock_availability_state": "available",
                        "available_stock_qty": product_available_qty.get(
                            stock_product.id,
                            0.0,
                        ),
                    }
                )
            else:
                line._write_internal(
                    {
                        "stock_availability_state": "unavailable",
                        "available_stock_qty": product_available_qty.get(
                            stock_product.id,
                            0.0,
                        ),
                    }
                )

        # --------------------------------------------------------
        # 7. Resultado general.
        # --------------------------------------------------------
        if has_insufficient_stock:

            self._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unavailable",
                }
            )

        else:

            self._write_internal(
                {
                    "stock_checked": True,
                    "stock_availability_state": "available",
                }
            )

        # --------------------------------------------------------
        # 8. Recargar para mostrar inmediatamente:
        #
        # - Disponible / No disponible
        # - Comprobar stock / Enviar mercadería
        # --------------------------------------------------------
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

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
        # La mercadería no puede enviarse hasta haber realizado
        # primero la comprobación de stock.
        # --------------------------------------------------------
        if not self.stock_checked:
            raise UserError(
                "Primero debe comprobar el stock antes de enviar la mercadería."
            )

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
        stock_product_by_line = {}

        for line in self.line_ids:

            if line.qty_sent <= 0:
                raise UserError(
                    f"La cantidad del producto {line.product_id.display_name} "
                    "debe ser mayor que cero."
                )

            # ----------------------------------------------------
            # Resolver el producto que realmente representa el
            # stock en el almacén origen.
            #
            # Por modelo   -> SIN CLASIFICAR
            # Por variante -> variante seleccionada
            # ----------------------------------------------------
            stock_product = line._get_stock_product_for_warehouse(
                self.source_warehouse_id
            )

            stock_product_by_line[line.id] = stock_product

            quantities_by_product.setdefault(stock_product, 0.0)
            quantities_by_product[stock_product] += line.qty_sent

        # --------------------------------------------------------
        # 7. VOLVER A COMPROBAR STOCK ANTES DEL ENVÍO
        #
        # Aunque el stock ya fue comprobado anteriormente,
        # volvemos a consultarlo porque otra operación podría
        # haber consumido mercadería mientras tanto.
        # --------------------------------------------------------
        Quant = self.env["stock.quant"]

        product_availability = {}
        product_available_qty = {}
        has_insufficient_stock = False

        for product, requested_qty in quantities_by_product.items():

            available_qty = Quant._get_available_quantity(
                product,
                self.source_location_id,
            )

            product_available_qty[product.id] = available_qty

            is_available = (
                float_compare(
                    available_qty,
                    requested_qty,
                    precision_rounding=product.uom_id.rounding,
                )
                >= 0
            )

            product_availability[product.id] = is_available

            if not is_available:
                has_insufficient_stock = True

        # --------------------------------------------------------
        # Actualizar nuevamente la disponibilidad de cada línea.
        # --------------------------------------------------------
        for line in self.line_ids:

            # Producto que realmente representa el stock en este almacén.
            # Por modelo   -> SIN CLASIFICAR
            # Por variante -> variante seleccionada
            stock_product = stock_product_by_line[line.id]

            if product_availability.get(stock_product.id):
                line._write_internal(
                    {
                        "stock_availability_state": "available",
                        "available_stock_qty": product_available_qty.get(
                            stock_product.id,
                            0.0,
                        ),
                    }
                )
            else:
                line._write_internal(
                    {
                        "stock_availability_state": "unavailable",
                        "available_stock_qty": product_available_qty.get(
                            stock_product.id,
                            0.0,
                        ),
                    }
                )

        # --------------------------------------------------------
        # Si el stock cambió después de la primera comprobación:
        #
        # - NO crear movimientos.
        # - NO descontar stock.
        # - volver a "Comprobar stock".
        # - mostrar qué producto ya no está disponible.
        # --------------------------------------------------------
        if has_insufficient_stock:

            self._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unavailable",
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        # --------------------------------------------------------
        # El stock continúa disponible.
        # Se mantiene habilitado y continúa el envío normal.
        # --------------------------------------------------------
        self._write_internal(
            {
                "stock_checked": True,
                "stock_availability_state": "available",
            }
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

            stock_product = stock_product_by_line[line.id]

            move_values.append(
                (
                    0,
                    0,
                    {
                        "product_id": stock_product.id,
                        "product_uom_qty": line.qty_sent,
                        "product_uom": stock_product.uom_id.id,
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
                # ========================================================
                # MOVIMIENTO TÉCNICO DEL TRF
                # Permite identificarlo y relacionarlo con el documento
                # comercial/operativo TRF/xxxxx.
                # ========================================================
                "is_store_transfer_technical": True,
                "store_transfer_id": self.id,
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
            # Guardar internamente la cantidad original y la cantidad en tránsito.
            line._write_internal(
                {
                    "original_qty_sent": line.qty_sent,
                    "qty_in_transit": line.qty_sent,
                }
            )

        # --------------------------------------------------------
        # 11. Registrar quién hizo el envío y cambiar el estado.
        # --------------------------------------------------------
        self._write_internal(
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

            self._write_internal(
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
        # PREPARAR LOS MOVIMIENTOS DE RECEPCIÓN
        #
        # Si la tienda destino recibe por variantes:
        # 1. Se retira del tránsito el producto enviado originalmente
        #    (por ejemplo: SIN CLASIFICAR).
        # 2. Se generan las variantes según la distribución manual
        #    registrada por la tienda destino.
        #
        # Si no trabaja por variantes, se mantiene el flujo normal.
        # --------------------------------------------------------
        move_values = []

        # Modo real de recepción seleccionado para esta transferencia.
        reception_mode = self._get_effective_reception_mode()

        # Ubicación desde donde saldrán los productos del picking
        # técnico de recepción.
        receipt_source_location = transit_location

        # --------------------------------------------------------
        # RECEPCIÓN POR VARIANTES
        # --------------------------------------------------------
        if reception_mode == "variant":

            # Usamos la ubicación virtual de Producción como punto técnico
            # para transformar el producto SIN CLASIFICAR en sus variantes.
            classification_location = self.env["stock.location"].search(
                [
                    ("usage", "=", "production"),
                    ("company_id", "in", [False, self.company_id.id]),
                ],
                limit=1,
            )

            if not classification_location:
                raise UserError(
                    "No se encontró una ubicación virtual de Producción "
                    "para realizar la distribución por variantes."
                )

            # El picking que ingresará a la tienda saldrá técnicamente
            # desde la ubicación de clasificación.
            receipt_source_location = classification_location

            # Movimientos que retirarán del tránsito el producto original.
            classification_move_values = []

            for line in self.line_ids:

                distribution = line.variant_distribution or []

                if not distribution:
                    raise UserError(
                        "Debes distribuir manualmente las unidades recibidas "
                        "entre las variantes antes de confirmar."
                    )

                distributed_qty = sum(
                    float(item.get("qty", 0.0)) for item in distribution
                )

                # La suma de las variantes debe ser exactamente igual
                # a la cantidad recibida físicamente.
                if (
                    float_compare(
                        distributed_qty,
                        line.qty_received,
                        precision_rounding=line.uom_id.rounding,
                    )
                    != 0
                ):
                    raise UserError(
                        "La distribución por variantes no coincide con "
                        "la cantidad recibida."
                    )

                # ----------------------------------------------------
                # Obtener técnicamente el almacén origen.
                #
                # El usuario destino no necesita tener acceso directo
                # al almacén que realizó el envío.
                # sudo() se usa únicamente para consultar la
                # configuración técnica del almacén origen.
                # ----------------------------------------------------
                source_warehouse = self.sudo().source_warehouse_id

                stock_product = line._get_stock_product_for_warehouse(
                    source_warehouse.sudo()
                )

                # ====================================================
                # RETIRAR DEL TRÁNSITO EL PRODUCTO REALMENTE ENVIADO
                #
                # Ejemplo:
                # 40 SIN CLASIFICAR
                # Tránsito -> ubicación técnica de clasificación
                # ====================================================
                classification_move_values.append(
                    {
                        # Producto real que se encuentra actualmente en tránsito.
                        "product_id": stock_product.id,
                        # Cantidad total que debe salir de tránsito para ser clasificada.
                        "product_uom_qty": line.qty_received,
                        # Unidad de medida del producto técnico.
                        "product_uom": stock_product.uom_id.id,
                        # Origen: ubicación de tránsito.
                        "location_id": transit_location.id,
                        # Destino técnico usado para realizar la clasificación.
                        "location_dest_id": classification_location.id,
                        # Empresa de la transferencia.
                        "company_id": self.company_id.id,
                    }
                )

                # ====================================================
                # 2. PREPARAR LAS VARIANTES QUE ENTRARÁN AL DESTINO
                # Ejemplo:
                # Blanco/S = 5
                # Blanco/M = 10
                # etc.
                # ====================================================
                for item in distribution:

                    variant_id = int(item.get("product_id") or 0)
                    variant_qty = float(item.get("qty") or 0.0)

                    if not variant_id or variant_qty <= 0:
                        continue

                    variant = self.env["product.product"].browse(variant_id)

                    if not variant.exists():
                        raise UserError(
                            "Una de las variantes seleccionadas ya no existe."
                        )

                    # Seguridad: solamente se permiten variantes
                    # pertenecientes al mismo modelo/producto plantilla.
                    if variant.product_tmpl_id != line.product_id.product_tmpl_id:
                        raise UserError(
                            "La variante %s no pertenece al mismo producto."
                            % variant.display_name
                        )

                    move_values.append(
                        (
                            0,
                            0,
                            {
                                "product_id": variant.id,
                                "product_uom_qty": variant_qty,
                                "product_uom": variant.uom_id.id,
                                "location_id": classification_location.id,
                                "location_dest_id": self.destination_location_id.id,
                            },
                        )
                    )

            # ========================================================
            # EJECUTAR LA SALIDA DEL PRODUCTO ORIGINAL DEL TRÁNSITO
            # ========================================================
            classification_moves = self.env["stock.move"].create(
                classification_move_values
            )

            classification_moves._action_confirm()
            classification_moves._action_assign()

            for move in classification_moves:
                move.quantity = move.product_uom_qty

            classification_moves._action_done()

        # --------------------------------------------------------
        # RECEPCIÓN POR MODELO
        #
        # Se mueve exactamente el mismo producto técnico que fue
        # enviado al tránsito.
        #
        # Ejemplo:
        # Huánuco trabaja Por modelo:
        # SIN CLASIFICAR -> Tránsito -> Destino
        # --------------------------------------------------------
        else:

            # Lectura técnica del almacén origen.
            # El usuario destino no necesita acceso administrativo
            # al almacén que realizó el envío.
            source_warehouse = self.sudo().source_warehouse_id

            for line in self.line_ids:

                # Obtener el producto que realmente se encuentra en tránsito.
                stock_product = line._get_stock_product_for_warehouse(
                    source_warehouse.sudo()
                )

                move_values.append(
                    (
                        0,
                        0,
                        {
                            "product_id": stock_product.id,
                            "product_uom_qty": line.qty_received,
                            "product_uom": stock_product.uom_id.id,
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
                # ========================================================
                # MOVIMIENTO TÉCNICO DEL TRF
                # Recepción desde tránsito hacia el almacén destino.
                # ========================================================
                "is_store_transfer_technical": True,
                "store_transfer_id": self.id,
                "picking_type_id": picking_type.id,
                "location_id": receipt_source_location.id,
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
        self._write_internal(
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
                        # ========================================================
                        # MOVIMIENTO TÉCNICO DE CORRECCIÓN
                        # Devuelve la diferencia desde tránsito al almacén origen.
                        # ========================================================
                        "is_store_transfer_technical": True,
                        "store_transfer_id": self.id,
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
                        # ========================================================
                        # MOVIMIENTO TÉCNICO DE CORRECCIÓN
                        # Envía al tránsito la cantidad adicional necesaria.
                        # ========================================================
                        "is_store_transfer_technical": True,
                        "store_transfer_id": self.id,
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

            # Actualizar internamente la cantidad que queda realmente en tránsito.
            line._write_internal(
                {
                    "qty_in_transit": line.qty_sent,
                }
            )

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

        self._write_internal(values)

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

    # ============================================================
    # CREAR / ABRIR DEVOLUCIÓN DE UNA TRANSFERENCIA RECIBIDA
    #
    # La devolución solo puede ser iniciada por el almacén que
    # recibió originalmente la mercadería.
    #
    # Ejemplo:
    # TRF: HUANUCO -> WH
    # DEV: WH -> HUANUCO
    #
    # Si ya existe una devolución activa, se abre esa misma para
    # evitar crear documentos duplicados.
    # ============================================================
    def action_create_return(self):
        self.ensure_one()

        # --------------------------------------------------------
        # La transferencia original debe estar recibida.
        # --------------------------------------------------------
        if self.state != "received":
            raise UserError(
                "Solo se pueden devolver transferencias que estén Recibidas."
            )

        # --------------------------------------------------------
        # Solo el almacén que recibió puede iniciar la devolución.
        # --------------------------------------------------------
        if not self.is_destination_user:
            raise UserError(
                "Solo el almacén que recibió la mercadería puede "
                "iniciar la devolución."
            )

        Return = self.env["dt.store.transfer.return"]
        ReturnLine = self.env["dt.store.transfer.return.line"]

        # --------------------------------------------------------
        # Si ya existe una DEV activa, abrimos esa misma.
        # Así evitamos crear varias devoluciones simultáneas.
        # --------------------------------------------------------
        active_return = Return.search(
            [
                ("original_transfer_id", "=", self.id),
                ("state", "in", ("draft", "waiting", "observed")),
            ],
            limit=1,
        )

        if active_return:
            return {
                "type": "ir.actions.act_window",
                "name": active_return.name,
                "res_model": "dt.store.transfer.return",
                "res_id": active_return.id,
                "view_mode": "form",
                "target": "current",
            }

        # ========================================================
        # PREPARAR PRODUCTOS QUE TODAVÍA PUEDEN DEVOLVERSE
        #
        # Recibido originalmente - devoluciones ya terminadas.
        # ========================================================
        return_lines = []

        for line in self.line_ids:

            previous_return_lines = ReturnLine.search(
                [
                    ("original_transfer_line_id", "=", line.id),
                    ("return_id.state", "=", "received"),
                ]
            )

            already_returned = sum(previous_return_lines.mapped("qty_received"))

            available_qty = max(
                line.qty_received - already_returned,
                0.0,
            )

            # Si este producto ya fue devuelto completamente,
            # no necesitamos mostrarlo en una nueva devolución.
            if (
                float_compare(
                    available_qty,
                    0.0,
                    precision_rounding=line.uom_id.rounding,
                )
                <= 0
            ):
                continue

            return_lines.append(
                (
                    0,
                    0,
                    {
                        "original_transfer_line_id": line.id,
                        "qty_to_return": 0.0,
                    },
                )
            )

        if not return_lines:
            raise UserError(
                "Todos los productos de esta transferencia ya fueron devueltos."
            )

        # ========================================================
        # CREAR DEVOLUCIÓN
        #
        # El origen y destino quedan invertidos respecto al TRF.
        # ========================================================
        return_doc = Return.create(
            {
                "company_id": self.company_id.id,
                "original_transfer_id": self.id,
                # El almacén que recibió ahora será quien devuelve.
                "source_warehouse_id": self.destination_warehouse_id.id,
                "source_location_id": self.destination_location_id.id,
                # El almacén que envió originalmente ahora recibe.
                "destination_warehouse_id": self.source_warehouse_id.id,
                "destination_location_id": self.source_location_id.id,
                "line_ids": return_lines,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": return_doc.name,
            "res_model": "dt.store.transfer.return",
            "res_id": return_doc.id,
            "view_mode": "form",
            "target": "current",
        }

    # ============================================================
    # ABRIR ASISTENTE DE ANULACIÓN
    #
    # Muestra una ventana emergente para que el usuario indique
    # obligatoriamente el motivo antes de anular el TRF.
    # ============================================================
    def action_open_cancel_wizard(self):
        self.ensure_one()

        # Una transferencia recibida ya no se anula.
        # En ese caso deberá utilizarse el flujo de devolución.
        if self.state == "received":
            raise UserError(
                "Una transferencia recibida no puede anularse. "
                "Debe realizarse una devolución."
            )

        if self.state == "cancelled":
            raise UserError("Esta transferencia ya se encuentra anulada.")

        # Solo el almacén origen puede iniciar la anulación.
        if not self.is_source_user:
            raise UserError(
                "Solo el almacén de origen puede anular esta transferencia."
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Anular transferencia",
            "res_model": "dt.store.transfer.cancel.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_transfer_id": self.id,
            },
        }

    # ============================================================
    # ANULAR TRANSFERENCIA
    #
    # Este método realiza la anulación real del documento.
    #
    # - Borrador:
    #   No existe movimiento de stock, por lo que solamente cambia
    #   el documento al estado "Anulada".
    #
    # - Por recibir / Observada:
    #   La mercadería que continúa en tránsito se devuelve
    #   automáticamente al almacén origen.
    #
    # - Recibida:
    #   No se puede anular porque el stock ya ingresó al destino.
    #   Ese caso se manejará posteriormente mediante devolución.
    #
    # El motivo será enviado desde el asistente de anulación.
    # ============================================================
    def action_cancel_with_reason(self, reason):
        self.ensure_one()

        # --------------------------------------------------------
        # VALIDAR MOTIVO
        # --------------------------------------------------------
        reason = (reason or "").strip()

        if not reason:
            raise UserError("Debe ingresar el motivo de la anulación.")

        # --------------------------------------------------------
        # VALIDAR ESTADO
        # --------------------------------------------------------
        if self.state == "cancelled":
            raise UserError("Esta transferencia ya se encuentra anulada.")

        if self.state == "received":
            raise UserError(
                "Una transferencia recibida no puede anularse. "
                "Debe realizarse una devolución."
            )

        if self.state not in ("draft", "waiting", "observed"):
            raise UserError(
                "La transferencia no se encuentra en un estado que permita anularla."
            )

        # --------------------------------------------------------
        # VALIDAR USUARIO
        #
        # La anulación corresponde al almacén que originó el envío.
        # --------------------------------------------------------
        if not self.is_source_user:
            raise UserError(
                "Solo el almacén de origen puede anular esta transferencia."
            )

        cancellation_picking = False

        # ========================================================
        # SI YA FUE ENVIADA:
        # DEVOLVER TODO LO QUE CONTINÚE EN TRÁNSITO
        # ========================================================
        if self.state in ("waiting", "observed"):

            transit_location = self.company_id.internal_transit_location_id

            if not transit_location:
                raise UserError(
                    "No se encontró la ubicación de tránsito de la empresa."
                )

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

            # ----------------------------------------------------
            # Preparar únicamente las cantidades que realmente
            # continúan técnicamente en tránsito.
            # ----------------------------------------------------
            move_values = []

            for line in self.line_ids:

                if (
                    float_compare(
                        line.qty_in_transit,
                        0.0,
                        precision_rounding=line.uom_id.rounding,
                    )
                    <= 0
                ):
                    continue

                move_values.append(
                    (
                        0,
                        0,
                        {
                            "product_id": line.product_id.id,
                            "product_uom_qty": line.qty_in_transit,
                            "product_uom": line.uom_id.id,
                            "location_id": transit_location.id,
                            "location_dest_id": self.source_location_id.id,
                        },
                    )
                )

            # ----------------------------------------------------
            # Crear un único movimiento técnico de devolución.
            # ----------------------------------------------------
            if move_values:

                cancellation_picking = self.env["stock.picking"].create(
                    {
                        # Identificarlo como movimiento técnico TRF.
                        "is_store_transfer_technical": True,
                        "store_transfer_id": self.id,
                        "picking_type_id": picking_type.id,
                        "location_id": transit_location.id,
                        "location_dest_id": self.source_location_id.id,
                        "origin": "%s - Anulación" % self.name,
                        "move_ids": move_values,
                    }
                )

                cancellation_picking.action_confirm()
                cancellation_picking.action_assign()

                for move in cancellation_picking.move_ids:
                    move.quantity = move.product_uom_qty

                result = cancellation_picking.button_validate()

                if result is not True:
                    raise UserError(
                        "Odoo requiere una validación adicional para "
                        "completar la devolución por anulación."
                    )

            # ----------------------------------------------------
            # Ya no queda mercadería de este TRF en tránsito.
            # ----------------------------------------------------
            for line in self.line_ids:
                # Al anular, ya no queda mercadería de este TRF en tránsito.
                line._write_internal(
                    {
                        "qty_in_transit": 0.0,
                    }
                )

        # ========================================================
        # REGISTRAR LA ANULACIÓN
        # ========================================================
        self._write_internal(
            {
                "state": "cancelled",
                "cancel_reason": reason,
                "cancelled_by_id": self.env.user.id,
                "cancelled_date": fields.Datetime.now(),
                "cancellation_picking_id": (
                    cancellation_picking.id if cancellation_picking else False
                ),
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Transferencia anulada",
                "message": (
                    "La transferencia fue anulada correctamente. "
                    "La mercadería en tránsito fue devuelta al almacén "
                    "de origen cuando correspondía."
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

    # ============================================================
    # ELIMINAR TRANSFERENCIA COMPLETA
    #
    # Solo se permite eliminar una TRF mientras permanezca
    # en estado Borrador.
    #
    # Una vez enviada, observada, recibida o anulada,
    # la transferencia debe conservarse por trazabilidad.
    # ============================================================
    def unlink(self):

        for transfer in self:

            if transfer.state != "draft":
                raise UserError(
                    "Solo se pueden eliminar transferencias que estén en Borrador."
                )

            # ----------------------------------------------------
            # Seguridad adicional para usuarios restringidos.
            # Solo el almacén origen puede eliminar su TRF.
            # ----------------------------------------------------
            if transfer._is_restricted_store_user():

                if not transfer.is_source_user:
                    raise UserError(
                        "Solo el almacén de origen puede eliminar "
                        "esta transferencia."
                    )

        return super().unlink()


class StoreTransferLine(models.Model):
    _name = "dt.store.transfer.line"
    _description = "Detalle de Transferencia entre Tiendas"
    _order = "id"

    # ============================================================
    # CREACIÓN SEGURA DE LÍNEAS TRF
    #
    # Un usuario de tienda únicamente puede agregar productos
    # mientras la transferencia esté en Borrador y sea el almacén
    # origen.
    #
    # No se permite crear manualmente cantidades técnicas como:
    # - cantidad inicial;
    # - cantidad en tránsito;
    # - cantidad recibida.
    # ============================================================

    @api.model_create_multi
    def create(self, vals_list):

        if self._is_restricted_store_user():

            for vals in vals_list:

                # ------------------------------------------------
                # SOLO CAMPOS OPERATIVOS DURANTE LA CREACIÓN
                # ------------------------------------------------
                protected_fields = {
                    "original_qty_sent",
                    "qty_in_transit",
                    "qty_received",
                }

                if set(vals) & protected_fields:
                    raise UserError(
                        "No puede establecer cantidades técnicas "
                        "al crear un producto de la transferencia."
                    )

                # ------------------------------------------------
                # LA LÍNEA DEBE PERTENECER A UN TRF
                # ------------------------------------------------
                transfer_id = vals.get("transfer_id")

                if not transfer_id:
                    raise UserError("La línea debe pertenecer a una transferencia.")

                transfer = self.env["dt.store.transfer"].browse(transfer_id)

                if not transfer.exists():
                    raise UserError("La transferencia indicada no existe.")

                # ------------------------------------------------
                # SOLO SE AGREGAN PRODUCTOS EN BORRADOR
                # ------------------------------------------------
                if transfer.state != "draft":
                    raise UserError(
                        "No puede agregar productos a una transferencia "
                        "que ya fue enviada."
                    )

                # ------------------------------------------------
                # SOLO EL ALMACÉN ORIGEN PUEDE AGREGAR PRODUCTOS
                # ------------------------------------------------
                if not transfer.is_source_user:
                    raise UserError(
                        "Solo el almacén origen puede agregar productos "
                        "a esta transferencia."
                    )

        lines = super().create(vals_list)

        # ========================================================
        # INVALIDAR COMPROBACIÓN AL AGREGAR PRODUCTOS
        #
        # Si se agrega una nueva línea a una TRF en Borrador,
        # la comprobación anterior deja de ser válida.
        # ========================================================
        draft_transfers = lines.mapped("transfer_id").filtered(
            lambda transfer: transfer.state == "draft"
        )

        if draft_transfers:

            draft_transfers._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unchecked",
                }
            )

            draft_transfers.mapped("line_ids")._write_internal(
                {
                    "stock_availability_state": "unchecked",
                    "available_stock_qty": 0.0,
                }
            )

        return lines

    # ============================================================
    # ELIMINAR PRODUCTO DEL TRF
    #
    # Si se elimina una línea en Borrador, cualquier comprobación
    # de stock anterior deja de ser válida.
    # ============================================================
    def unlink(self):

        draft_transfers = self.mapped("transfer_id").filtered(
            lambda transfer: transfer.state == "draft"
        )

        # --------------------------------------------------------
        # Seguridad para usuarios restringidos de tienda.
        # --------------------------------------------------------
        if self._is_restricted_store_user():

            for line in self:

                if line.transfer_id.state != "draft":
                    raise UserError(
                        "No puede eliminar productos de una transferencia "
                        "que ya fue enviada."
                    )

                if not line.transfer_id.is_source_user:
                    raise UserError(
                        "Solo el almacén origen puede eliminar productos "
                        "de esta transferencia."
                    )

        result = super().unlink()

        # --------------------------------------------------------
        # Invalidar la comprobación anterior.
        # --------------------------------------------------------
        if draft_transfers:

            draft_transfers._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unchecked",
                }
            )

            draft_transfers.mapped("line_ids")._write_internal(
                {
                    "stock_availability_state": "unchecked",
                    "available_stock_qty": 0.0,
                }
            )

        return result

    # ============================================================
    # SEGURIDAD DE ESCRITURA DE LAS LÍNEAS DEL TRF
    #
    # Reglas para usuarios de tienda:
    #
    # BORRADOR:
    # - Origen puede modificar producto y cantidad enviada.
    #
    # POR RECIBIR:
    # - Destino puede modificar únicamente cantidad recibida.
    #
    # OBSERVADA:
    # - Origen puede corregir únicamente cantidad enviada.
    #
    # RECIBIDA / ANULADA:
    # - Ninguna cantidad puede modificarse manualmente.
    #
    # Los campos técnicos se modifican únicamente mediante
    # _write_internal() desde los procesos oficiales del módulo.
    # ============================================================

    def _is_restricted_store_user(self):
        user = self.env.user

        return user.has_group(
            "pos_stock_restriccion_tienda.group_tienda_restringida"
        ) and not user.has_group("base.group_system")

    def _write_internal(self, vals):
        """Escritura interna para cantidades técnicas del TRF."""
        return super(StoreTransferLine, self).write(vals)

    def write(self, vals):

        fields_to_write = set(vals)

        # ========================================================
        # INVALIDAR COMPROBACIÓN DE STOCK
        #
        # Si en Borrador cambia el producto o la cantidad enviada,
        # la comprobación anterior deja de ser válida.
        # ========================================================
        must_reset_stock = bool({"product_id", "qty_sent"} & fields_to_write)

        draft_transfers = self.mapped("transfer_id").filtered(
            lambda transfer: transfer.state == "draft"
        )

        # --------------------------------------------------------
        # Administradores/TI mantienen comportamiento normal,
        # pero también deben invalidar una comprobación anterior.
        # --------------------------------------------------------
        if not self._is_restricted_store_user():

            result = super().write(vals)

            if must_reset_stock and draft_transfers:

                # Reiniciar estado general del TRF.
                draft_transfers._write_internal(
                    {
                        "stock_checked": False,
                        "stock_availability_state": "unchecked",
                    }
                )

                # Reiniciar disponibilidad de todas sus líneas.
                draft_transfers.mapped("line_ids")._write_internal(
                    {
                        "stock_availability_state": "unchecked",
                        "available_stock_qty": 0.0,
                    }
                )

            return result

        # --------------------------------------------------------
        # CAMPOS TÉCNICOS
        # Nunca deben modificarse manualmente desde una tienda.
        # --------------------------------------------------------
        protected_fields = {
            "transfer_id",
            "original_qty_sent",
            "qty_in_transit",
            "stock_availability_state",
            "variant_distribution",
        }

        if fields_to_write & protected_fields:
            raise UserError(
                "No puede modificar directamente datos técnicos " "de la transferencia."
            )

        # --------------------------------------------------------
        # VALIDAR CADA LÍNEA SEGÚN ESTADO Y ROL
        # --------------------------------------------------------
        for line in self:

            transfer = line.transfer_id

            # BORRADOR:
            # solo origen modifica producto y cantidad enviada.
            if transfer.state == "draft":

                if not transfer.is_source_user:
                    raise UserError(
                        "Solo el almacén origen puede modificar "
                        "los productos de esta transferencia."
                    )

                allowed_fields = {
                    "product_id",
                    "qty_sent",
                }

            # POR RECIBIR:
            # solo destino registra cantidad recibida.
            elif transfer.state == "waiting":

                if not transfer.is_destination_user:
                    raise UserError(
                        "Solo el almacén destino puede registrar "
                        "la cantidad recibida."
                    )

                allowed_fields = {
                    "qty_received",
                }

            # OBSERVADA:
            # solo origen corrige cantidad enviada.
            elif transfer.state == "observed":

                if not transfer.is_source_user:
                    raise UserError(
                        "Solo el almacén origen puede corregir " "la cantidad enviada."
                    )

                allowed_fields = {
                    "qty_sent",
                }

            # RECIBIDA / ANULADA
            else:
                raise UserError(
                    "Esta transferencia ya no permite modificar " "sus cantidades."
                )

            invalid_fields = fields_to_write - allowed_fields

            if invalid_fields:
                raise UserError(
                    "No tiene permiso para modificar esos datos " "de la transferencia."
                )

        result = super().write(vals)

        # --------------------------------------------------------
        # Si cambió producto o cantidad mientras estaba en Borrador,
        # obligamos a comprobar nuevamente el stock.
        # --------------------------------------------------------
        if must_reset_stock and draft_transfers:

            draft_transfers._write_internal(
                {
                    "stock_checked": False,
                    "stock_availability_state": "unchecked",
                }
            )

            draft_transfers.mapped("line_ids")._write_internal(
                {
                    "stock_availability_state": "unchecked",
                    "available_stock_qty": 0.0,
                }
            )

        return result

    def action_open_variant_distribution(self):
        self.ensure_one()

        transfer = self.transfer_id

        # Solo durante la recepción.
        if transfer.state != "waiting":
            raise UserError(
                "La distribución por variantes solo puede realizarse "
                "cuando la transferencia está Por recibir."
            )

        # Solo el almacén destino.
        if not transfer.is_destination_user:
            raise UserError(
                "Solo el almacén destino puede distribuir " "las variantes recibidas."
            )

        # La transferencia debe estar configurada para recibir
        # específicamente por variantes.
        if transfer._get_effective_reception_mode() != "variant":
            raise UserError("Primero seleccione Por variantes en Forma de recepción.")

        # Validamos que existan las variantes y que el usuario
        # tenga permiso para realizar la distribución.
        self.get_variant_distribution_info()

        # Abrimos la interfaz dinámica de distribución.
        return {
            "type": "ir.actions.client",
            "tag": "dt_variant_distribution",
            "name": "Distribuir variantes",
            "params": {
                "line_id": self.id,
            },
            "target": "new",
        }

    # ============================================================
    # PRODUCTO OPERATIVO SEGÚN EL MODO DEL ALMACÉN
    #
    # - Almacén por modelo:
    #     utiliza la variante técnica SIN CLASIFICAR.
    #
    # - Almacén por variantes:
    #     utiliza la variante seleccionada normalmente.
    #
    # - Almacén mixto:
    #     por ahora conserva el producto de la línea.
    #     Más adelante se definirá el modo de salida de TDA DIGITAL.
    # ============================================================

    def _get_stock_product_for_warehouse(self, warehouse):
        self.ensure_one()

        product = self.product_id

        if not warehouse:
            return product

        # Compatibilidad si dt_catalogo_comercial no estuviera instalado.
        if "product_control_mode" not in warehouse._fields:
            return product

        # Solo los almacenes que trabajan por MODELO utilizan
        # stock técnico SIN CLASIFICAR.
        if warehouse.product_control_mode != "model":
            return product

        Product = self.env["product.product"]

        if "is_unclassified_variant" not in Product._fields:
            raise UserError(
                "El almacén trabaja por modelo, pero no está disponible "
                "la configuración de stock SIN CLASIFICAR."
            )

        template = product.product_tmpl_id

        unclassified_variant = template.with_context(
            active_test=False
        ).product_variant_ids.filtered(
            lambda variant: (variant.active and variant.is_unclassified_variant)
        )

        if len(unclassified_variant) != 1:
            raise UserError(
                f"El producto {template.display_name} debe tener exactamente "
                "una variante técnica SIN CLASIFICAR antes de operar "
                "en un almacén configurado Por modelo."
            )

        return unclassified_variant

    # ============================================================
    # DATOS PARA DISTRIBUCIÓN DE RECEPCIÓN POR VARIANTES
    #
    # Devuelve las variantes reales y activas del modelo.
    # Se utilizará para construir dinámicamente la matriz
    # Color x Talla en el almacén destino.
    # ============================================================
    def get_variant_distribution_info(self):
        self.ensure_one()

        transfer = self.transfer_id

        # La matriz solo puede utilizarse cuando esta recepción
        # concretamente trabaja por variantes.
        if transfer._get_effective_reception_mode() != "variant":
            raise UserError(
                "Esta transferencia está configurada para recibirse Por modelo."
            )

        # La distribución solo corresponde durante la recepción.
        if transfer.state != "waiting":
            raise UserError(
                "La distribución por variantes solo puede realizarse "
                "cuando la transferencia está Por recibir."
            )

        # Solo el almacén destino puede realizar la clasificación.
        if not transfer.is_destination_user:
            raise UserError(
                "Solo el almacén destino puede distribuir las variantes recibidas."
            )

        template = self.product_id.product_tmpl_id

        variants = template.product_variant_ids.filtered("active")

        # ------------------------------------------------------------
        # Excluir la variante técnica SIN CLASIFICAR.
        #
        # No existe dependencia obligatoria con dt_catalogo_comercial,
        # por eso primero comprobamos que el campo esté disponible.
        # ------------------------------------------------------------
        if "is_unclassified_variant" in variants._fields:
            variants = variants.filtered(
                lambda product: not product.is_unclassified_variant
            )

        variant_data = []

        for variant in variants:

            attributes = []

            for value in variant.product_template_variant_value_ids:
                attributes.append(
                    {
                        "attribute_id": value.attribute_id.id,
                        "attribute_name": value.attribute_id.name,
                        "value_id": value.product_attribute_value_id.id,
                        "value_name": value.name,
                    }
                )

            variant_data.append(
                {
                    "product_id": variant.id,
                    "display_name": variant.display_name,
                    "attributes": attributes,
                }
            )

        return {
            "line_id": self.id,
            "template_id": template.id,
            "template_name": template.display_name,
            "qty_sent": self.qty_sent,
            "qty_received": self.qty_received,
            "distribution": self.variant_distribution or [],
            "variants": variant_data,
        }

    # ============================================================
    # CAMPOS DE LA LÍNEA DE TRANSFERENCIA
    # ============================================================

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

    # ============================================================
    # DISPONIBILIDAD DEL PRODUCTO
    # ============================================================
    stock_availability_state = fields.Selection(
        [
            ("unchecked", "Sin comprobar"),
            ("available", "Disponible"),
            ("unavailable", "No disponible"),
        ],
        string="Disponibilidad",
        default="unchecked",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # STOCK DISPONIBLE EN EL ALMACÉN DE ORIGEN
    #
    # Se guarda al momento de comprobar stock.
    # Corresponde únicamente a la ubicación origen de la TRF,
    # no al stock total de todos los almacenes.
    # ============================================================
    available_stock_qty = fields.Float(
        string="Stock disponible",
        readonly=True,
        copy=False,
    )

    original_qty_sent = fields.Float(
        string="Cantidad inicial",
        readonly=True,
        copy=False,
    )

    # ============================================================
    # CANTIDAD ACTUALMENTE EN TRÁNSITO
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

    # ============================================================
    # DISTRIBUCIÓN DE RECEPCIÓN POR VARIANTES
    #
    # Se utiliza cuando el almacén destino trabaja por variantes
    # o en modo mixto, por ejemplo TDA DIGITAL.
    #
    # Ejemplo:
    # [
    #     {"product_id": 101, "qty": 5},
    #     {"product_id": 102, "qty": 10},
    # ]
    #
    # El producto de la línea sigue representando el modelo enviado.
    # Las variantes exactas serán definidas por el almacén receptor.
    # ============================================================
    variant_distribution = fields.Json(
        string="Distribución por variantes",
        default=list,
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
    # GUARDAR DISTRIBUCIÓN DE RECEPCIÓN POR VARIANTES
    #
    # Valida que:
    # - solo el almacén destino pueda distribuir;
    # - la transferencia esté Por recibir;
    # - las variantes pertenezcan al mismo modelo;
    # - no existan cantidades negativas;
    # - la suma distribuida sea exactamente igual a lo enviado.
    # ============================================================
    def save_variant_distribution(self, distribution):
        self.ensure_one()

        transfer = self.transfer_id

        # La matriz solo puede utilizarse cuando esta recepción
        # concretamente trabaja por variantes.
        if transfer._get_effective_reception_mode() != "variant":
            raise UserError(
                "Esta transferencia está configurada para recibirse Por modelo."
            )

        if transfer.state != "waiting":
            raise UserError(
                "La distribución por variantes solo puede registrarse "
                "cuando la transferencia está Por recibir."
            )

        if not transfer.is_destination_user:
            raise UserError(
                "Solo el almacén destino puede registrar "
                "la distribución por variantes."
            )

        if not isinstance(distribution, list):
            raise ValidationError("La distribución recibida no es válida.")

        template = self.product_id.product_tmpl_id

        valid_variants = template.product_variant_ids.filtered("active")

        # ------------------------------------------------------------
        # La variante técnica SIN CLASIFICAR no puede utilizarse
        # como una variante elegible dentro de la distribución.
        # ------------------------------------------------------------
        if "is_unclassified_variant" in valid_variants._fields:
            valid_variants = valid_variants.filtered(
                lambda product: not product.is_unclassified_variant
            )

        valid_variant_ids = set(valid_variants.ids)

        clean_distribution = []
        total_distributed = 0.0
        used_product_ids = set()

        for item in distribution:

            if not isinstance(item, dict):
                raise ValidationError("Existe una línea inválida en la distribución.")

            product_id = item.get("product_id")
            qty = item.get("qty", 0.0)

            if not product_id:
                continue

            try:
                qty = float(qty or 0.0)
            except (TypeError, ValueError):
                raise ValidationError(
                    "Existe una cantidad inválida en la distribución."
                )

            if qty < 0:
                raise ValidationError(
                    "Las cantidades por variante no pueden ser negativas."
                )

            # Las cantidades cero no necesitan almacenarse.
            if (
                float_compare(
                    qty,
                    0.0,
                    precision_rounding=self.uom_id.rounding,
                )
                == 0
            ):
                continue

            if product_id not in valid_variant_ids:
                raise ValidationError(
                    "Una de las variantes no pertenece al producto enviado."
                )

            if product_id in used_product_ids:
                raise ValidationError(
                    "Una variante aparece repetida en la distribución."
                )

            used_product_ids.add(product_id)

            clean_distribution.append(
                {
                    "product_id": product_id,
                    "qty": qty,
                }
            )

            total_distributed += qty

        # La suma Color x Talla debe coincidir exactamente con lo enviado.
        if (
            float_compare(
                total_distributed,
                self.qty_sent,
                precision_rounding=self.uom_id.rounding,
            )
            != 0
        ):
            raise ValidationError(
                _(
                    "La distribución por variantes debe sumar exactamente %(sent)s. "
                    "Actualmente suma %(distributed)s."
                )
                % {
                    "sent": self.qty_sent,
                    "distributed": total_distributed,
                }
            )

        # Escritura interna controlada.
        # qty_received queda sincronizado con el total de la matriz.
        self._write_internal(
            {
                "variant_distribution": clean_distribution,
                "qty_received": total_distributed,
            }
        )

        return {
            "success": True,
            "qty_sent": self.qty_sent,
            "qty_received": total_distributed,
            "distribution": clean_distribution,
        }

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
