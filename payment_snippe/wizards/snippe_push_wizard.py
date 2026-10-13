import re

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from odoo.addons.payment_snippe import const


class SnippePushWizard(models.TransientModel):
    _name = 'payment.snippe.push.wizard'
    _description = "Request a mobile money payment through Snippe"

    move_id = fields.Many2one('account.move', string="Invoice", required=True, readonly=True)
    partner_id = fields.Many2one(related='move_id.partner_id')
    currency_id = fields.Many2one(related='move_id.currency_id')
    amount_residual = fields.Monetary(related='move_id.amount_residual')
    phone = fields.Char(
        string="Mobile money number",
        help="The customer approves the payment with their PIN on this phone.",
        compute='_compute_phone', store=True, readonly=False,
    )
    amount = fields.Monetary(
        string="Amount",
        compute='_compute_amount', store=True, readonly=False,
    )

    @api.depends('partner_id')
    def _compute_phone(self):
        for wizard in self:
            wizard.phone = wizard.partner_id.mobile or wizard.partner_id.phone

    @api.depends('move_id')
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = wizard.move_id.amount_residual

    def _normalize_phone(self, phone):
        """ Return `phone` as Snippe takes it: 255 followed by the nine digits of the number.

        Spaces, dashes, brackets and a leading + or 00 are dropped, and a local number starting
        with 0 gets the country code.

        :param str phone: The number as typed, such as `0712 345 678` or `+255 712 345 678`.
        :return: The number, such as `255712345678`.
        :rtype: str
        :raise UserError: If the number is not a Tanzanian mobile number.
        """
        digits = re.sub(r'[\s\-().]', '', phone or '').removeprefix('+')
        if digits.startswith('00'):
            digits = digits[2:]
        if digits.startswith('0'):
            digits = const.PHONE_COUNTRY_CODE + digits[1:]
        if not re.fullmatch(const.PHONE_PATTERN, digits):
            raise UserError(_(
                "%(phone)s is not a Tanzanian mobile number. Enter it as 0712345678 or"
                " +255712345678.",
                phone=phone,
            ))
        return digits

    def action_send(self):
        """ Send the PIN prompt and record it as a payment transaction on the invoice.

        When the customer approves, Snippe's webhook marks the transaction done and Odoo registers
        and reconciles the payment, as for any online payment.
        """
        self.ensure_one()
        move = self.move_id
        if not (self.phone or '').strip():
            raise UserError(_("Enter the customer's mobile money number."))
        phone = self._normalize_phone(self.phone)
        if not move.snippe_can_request_payment:
            raise UserError(_("This invoice cannot be paid by mobile money through Snippe."))
        if float_compare(self.amount, 0, precision_rounding=self.currency_id.rounding) <= 0:
            raise UserError(_("Enter an amount to collect."))
        if float_compare(
            self.amount, move.amount_residual, precision_rounding=self.currency_id.rounding
        ) > 0:
            raise UserError(_("The amount is more than this invoice still owes."))
        provider = move._snippe_provider()
        if not provider:
            raise UserError(_("Set up and enable the Snippe payment provider first."))
        payment_method = provider.payment_method_ids.filtered(
            lambda m: m.code == 'snippe_mobile_money'
        )[:1]
        if not payment_method:
            raise UserError(_("Turn on mobile money in the Snippe payment provider first."))

        tx_model = self.env['payment.transaction'].sudo()
        tx = tx_model.create({
            'provider_id': provider.id,
            'payment_method_id': payment_method.id,
            'reference': tx_model._compute_reference(
                provider.code, invoice_ids=[Command.set(move.ids)]
            ),
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_id': move.partner_id.id,
            'operation': 'online_direct',
            'invoice_ids': [Command.set(move.ids)],
        })
        tx._snippe_request_mobile_money(phone)
        move.message_post(body=_(
            "Mobile money prompt for %(amount)s sent to %(phone)s (transaction %(ref)s).",
            amount=self.currency_id.format(self.amount), phone=phone, ref=tx.reference,
        ))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Prompt sent. The invoice updates once the customer approves it."),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
