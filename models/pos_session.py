from odoo import models, api, _
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def set_opening_control(self, session_id, cash_register_balance_start, notes):
        session = self.browse(session_id)

        # Si NO es administrador de Punto de Venta, validamos el monto
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            last_session = self.search(
                [
                    ("config_id", "=", session.config_id.id),
                    ("state", "=", "closed"),
                    ("id", "!=", session.id),
                ],
                order="stop_at desc, id desc",
                limit=1,
            )

            expected_balance = (
                last_session.cash_register_balance_end_real if last_session else 0.0
            )

            if abs(cash_register_balance_start - expected_balance) > 0.01:
                raise UserError(
                    _(
                        "No tienes permisos para modificar el monto de apertura. Debe ser exactamente %s.",
                        expected_balance,
                    )
                )

        return super(PosSession, self).set_opening_control(
            session_id, cash_register_balance_start, notes
        )
