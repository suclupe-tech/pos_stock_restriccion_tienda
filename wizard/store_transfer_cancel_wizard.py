from odoo import fields, models
from odoo.exceptions import UserError


class StoreTransferCancelWizard(models.TransientModel):
    _name = "dt.store.transfer.cancel.wizard"
    _description = "Asistente de anulación de transferencia"

    # ============================================================
    # TRANSFERENCIA A ANULAR
    #
    # Se cargará automáticamente desde el TRF que tenga abierto
    # el usuario al pulsar el botón "Anular transferencia".
    # ============================================================
    transfer_id = fields.Many2one(
        "dt.store.transfer",
        string="Transferencia",
        required=True,
        readonly=True,
    )

    # ============================================================
    # MOTIVO OBLIGATORIO
    #
    # Este texto quedará registrado permanentemente en el TRF
    # para conservar la trazabilidad de la anulación.
    # ============================================================
    reason = fields.Text(
        string="Motivo de anulación",
        required=True,
    )

    # ============================================================
    # CONFIRMAR ANULACIÓN
    #
    # El asistente no mueve stock directamente.
    # Llama al método central de dt.store.transfer, que se encarga
    # de validar el estado y devolver la mercadería cuando
    # todavía se encuentre en tránsito.
    # ============================================================
    def action_confirm_cancel(self):
        self.ensure_one()

        reason = (self.reason or "").strip()

        if not reason:
            raise UserError("Debe ingresar el motivo de la anulación.")

        return self.transfer_id.action_cancel_with_reason(reason)
    