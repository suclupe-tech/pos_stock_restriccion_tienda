from odoo import fields, models
from odoo.exceptions import UserError


class StoreTransferCancelWizard(models.TransientModel):
    _name = "dt.store.transfer.cancel.wizard"
    _description = "Asistente de anulación de transferencia o devolución"

    # ============================================================
    # DOCUMENTO A ANULAR
    #
    # El mismo asistente sirve para:
    # - TRF/xxxxx  -> transfer_id
    # - DEV/xxxxx  -> return_id
    #
    # Solo uno de los dos debe venir informado.
    # ============================================================

    transfer_id = fields.Many2one(
        "dt.store.transfer",
        string="Transferencia",
        readonly=True,
    )

    return_id = fields.Many2one(
        "dt.store.transfer.return",
        string="Devolución",
        readonly=True,
    )

    # ============================================================
    # MOTIVO OBLIGATORIO
    #
    # El motivo quedará registrado en el documento correspondiente
    # para mantener la trazabilidad de la anulación.
    # ============================================================

    reason = fields.Text(
        string="Motivo de anulación",
        required=True,
    )

    # ============================================================
    # CONFIRMAR ANULACIÓN
    #
    # El wizard no mueve stock directamente.
    # Delega la operación al TRF o DEV correspondiente.
    # ============================================================

    def action_confirm_cancel(self):
        self.ensure_one()

        reason = (self.reason or "").strip()

        if not reason:
            raise UserError("Debe ingresar el motivo de la anulación.")

        # --------------------------------------------------------
        # Evitar que el asistente tenga dos documentos a la vez.
        # --------------------------------------------------------
        if self.transfer_id and self.return_id:
            raise UserError(
                "El asistente no puede anular una transferencia "
                "y una devolución al mismo tiempo."
            )

        # --------------------------------------------------------
        # ANULACIÓN DE TRF
        # --------------------------------------------------------
        if self.transfer_id:
            return self.transfer_id.action_cancel_with_reason(reason)

        # --------------------------------------------------------
        # ANULACIÓN DE DEV
        # --------------------------------------------------------
        if self.return_id:
            return self.return_id.action_cancel_with_reason(reason)

        raise UserError(
            "No se encontró ningún documento para anular."
        )