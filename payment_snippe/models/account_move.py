from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    snippe_can_request_payment = fields.Boolean(compute='_compute_snippe_can_request_payment')

    @api.depends(
        'move_type', 'state', 'payment_state', 'amount_residual', 'currency_id', 'company_id'
    )
    def _compute_snippe_can_request_payment(self):
        """ An open customer invoice in shillings can be paid by a PIN prompt, when Snippe is set
        up for its company. """
        open_moves = self.filtered(lambda m: (
            m.move_type == 'out_invoice'
            and m.state == 'posted'
            and m.payment_state in ('not_paid', 'partial')
            and m.amount_residual > 0
            and m.currency_id.name == 'TZS'
        ))
        (self - open_moves).snippe_can_request_payment = False
        for move in open_moves:
            move.snippe_can_request_payment = bool(move._snippe_provider())

    def _snippe_provider(self):
        """ The Snippe provider that can collect for this invoice's company, if any. """
        self.ensure_one()
        return self.env['payment.provider'].sudo().search([
            ('code', '=', 'snippe'),
            ('state', 'in', ('enabled', 'test')),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def action_snippe_request_payment(self):
        """ Open the wizard that sends the customer a mobile money PIN prompt. """
        self.ensure_one()
        if not self.snippe_can_request_payment:
            raise UserError(_("This invoice cannot be paid by mobile money through Snippe."))
        return {
            'name': _("Request mobile money payment"),
            'type': 'ir.actions.act_window',
            'res_model': 'payment.snippe.push.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }
