import hashlib
import logging

from werkzeug.urls import url_encode, url_join

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_snippe import const
from odoo.addons.payment_snippe.controllers.main import SnippeController


_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    snippe_session_reference = fields.Char(
        string="Snippe Checkout Session",
        help="The Snippe checkout session the customer was sent to, when they paid through a"
             " link.",
        readonly=True,
        copy=False,
    )

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _snippe_amount(self):
        """ Return the amount in whole shillings, as Snippe takes it.

        Note: self.ensure_one()

        :return: The amount in shillings.
        :rtype: int
        :raise UserError: If the amount has cents or is below Snippe's minimum.
        """
        self.ensure_one()
        amount = self.currency_id.round(self.amount)
        whole = int(round(amount))
        if float_compare(amount, whole, precision_digits=self.currency_id.decimal_places) != 0:
            raise UserError("Snippe: " + _(
                "Mobile money collects whole shillings. Round %(amount)s to a whole amount.",
                amount=amount,
            ))
        if whole < const.MINIMUM_AMOUNT:
            raise UserError("Snippe: " + _(
                "Snippe collects at least %(minimum)s shillings.", minimum=const.MINIMUM_AMOUNT,
            ))
        return whole

    def _snippe_idempotency_key(self):
        """ Return the `Idempotency-Key` that makes a retried request for this transaction safe.

        The reference is used as is when Snippe accepts its length, else a digest of it.

        Note: self.ensure_one()

        :return: A key unique to this transaction, within Snippe's length limit.
        :rtype: str
        """
        self.ensure_one()
        if len(self.reference) <= const.IDEMPOTENCY_KEY_MAX_LENGTH:
            return self.reference
        digest = hashlib.sha256(self.reference.encode()).hexdigest()
        return digest[:const.IDEMPOTENCY_KEY_MAX_LENGTH]

    def _snippe_webhook_url(self):
        """ Return the URL Snippe posts this transaction's payment events to. """
        return url_join(self.provider_id.get_base_url(), SnippeController._webhook_url)

    def _get_specific_rendering_values(self, processing_values):
        """ Override of `payment` to open a Snippe payment link for the customer.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the
                                       transaction.
        :return: The URL of the hosted payment page, for the redirect form.
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'snippe':
            return res

        base_url = self.provider_id.get_base_url()
        # The phone is left for the customer to type on the payment page: a number
        # Snippe cannot read would refuse the whole link.
        customer = {
            key: value for key, value in (
                ('name', self.partner_name), ('email', self.partner_email),
            ) if value
        }
        payload = {
            'amount': self._snippe_amount(),
            'currency': self.currency_id.name,
            'allowed_methods': const.ALLOWED_METHODS.get(
                self.payment_method_code, ['mobile_money', 'card']
            ),
            'customer': customer,
            'description': self.reference,
            'redirect_url': url_join(base_url, SnippeController._return_url)
                + '?' + url_encode({'reference': self.reference}),
            'webhook_url': self._snippe_webhook_url(),
            'metadata': {'odoo_reference': self.reference},
            'expires_in': const.SESSION_EXPIRES_IN,
        }
        session = self.provider_id._snippe_make_request(
            '/api/v1/sessions', payload=payload, idempotency_key=self._snippe_idempotency_key()
        )
        payment_url = session.get('payment_link_url') or session.get('checkout_url')
        if not payment_url:
            raise ValidationError("Snippe: " + _("Snippe did not return a payment link."))
        self.snippe_session_reference = session.get('reference')
        return {'api_url': payment_url}

    def _snippe_request_mobile_money(self, phone):
        """ Send a mobile money PIN prompt to `phone` for this transaction.

        Works on any handset: the customer approves it with their PIN, and Snippe reports the
        outcome to the webhook like any other payment.

        Note: self.ensure_one()

        :param str phone: The customer's mobile money number, as 255 followed by nine digits.
        :raise UserError: If the customer has no email to give Snippe.
        """
        self.ensure_one()
        email = self.partner_email or self.company_id.email
        if not email:
            raise UserError("Snippe: " + _(
                "Add an email to the customer or to your company. Snippe asks for one with every"
                " mobile money request."
            ))
        first_name, last_name = payment_utils.split_partner_name(self.partner_name or '')
        first_name = first_name or last_name or self.company_id.name
        payload = {
            'payment_type': 'mobile',
            'details': {'amount': self._snippe_amount(), 'currency': self.currency_id.name},
            'phone_number': phone,
            'customer': {
                'firstname': first_name,
                'lastname': last_name or first_name,
                'email': email,
            },
            'webhook_url': self._snippe_webhook_url(),
            'metadata': {'odoo_reference': self.reference},
        }
        payment = self.provider_id._snippe_make_request(
            '/v1/payments', payload=payload, idempotency_key=self._snippe_idempotency_key()
        )
        self.provider_reference = payment.get('reference')
        self._set_pending(_("Mobile money prompt sent to %s.", phone))

    # === BUSINESS METHODS - NOTIFICATIONS === #

    @api.model
    def _snippe_normalize_payment(self, data):
        """ Read a Snippe payment in either API version into one shape.

        Snippe answers in the version the merchant chose: 2026-01-25 nests the amount, 2026-01-01
        has it flat.

        :param dict data: A payment from a webhook or from the payment lookup.
        :return: The reference, status, amount, currency, metadata and failure reason.
        :rtype: dict
        """
        amount = data.get('amount')
        currency = data.get('currency')
        if isinstance(amount, dict):
            currency = amount.get('currency')
            amount = amount.get('value')
        return {
            'reference': data.get('reference'),
            'status': (data.get('status') or '').lower(),
            'amount': amount,
            'currency': currency,
            'metadata': data.get('metadata') or {},
            'failure_reason': data.get('failure_reason'),
        }

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of `payment` to find the transaction named in Snippe's metadata.

        :param str provider_code: The code of the provider that handled the transaction.
        :param dict notification_data: `odoo_reference` and Snippe's payment `reference`.
        :return: The transaction.
        :rtype: recordset of `payment.transaction`
        :raise ValidationError: If the data name no transaction.
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'snippe' or len(tx) == 1:
            return tx

        reference = notification_data.get('odoo_reference')
        if not reference:
            raise ValidationError("Snippe: " + _("Received data with missing reference."))
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'snippe')])
        if not tx:
            raise ValidationError(
                "Snippe: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """ Override of `payment` to settle the transaction from what Snippe says now.

        The notification only says which payment to look at. Its state is read back from Snippe,
        and must name this transaction, its amount and its currency, before anything changes.

        Note: self.ensure_one()

        :param dict notification_data: Snippe's payment `reference`.
        :raise ValidationError: If Snippe's payment is not this transaction's.
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'snippe':
            return

        snippe_reference = notification_data.get('reference')
        if not snippe_reference:
            raise ValidationError("Snippe: " + _("Received data with missing payment reference."))
        payment = self._snippe_normalize_payment(self.provider_id._snippe_make_request(
            f'/v1/payments/{snippe_reference}', method='GET'
        ))

        if payment['metadata'].get('odoo_reference') != self.reference:
            raise ValidationError("Snippe: " + _(
                "Payment %(payment)s does not belong to transaction %(tx)s.",
                payment=snippe_reference, tx=self.reference,
            ))
        if payment['currency'] != self.currency_id.name or float_compare(
            payment['amount'] or 0, self.amount, precision_digits=self.currency_id.decimal_places
        ) != 0:
            raise ValidationError("Snippe: " + _(
                "Payment %(payment)s is for %(amount)s %(currency)s, not this transaction's"
                " amount.",
                payment=snippe_reference, amount=payment['amount'], currency=payment['currency'],
            ))

        self.provider_reference = snippe_reference
        status = payment['status']
        if status in const.PAYMENT_STATUS_MAPPING['pending']:
            self._set_pending()
        elif status in const.PAYMENT_STATUS_MAPPING['done']:
            self._set_done()
        elif status in const.PAYMENT_STATUS_MAPPING['cancel']:
            self._set_canceled()
        elif status in const.PAYMENT_STATUS_MAPPING['error']:
            self._set_error(payment['failure_reason'] or _(
                "The payment did not go through (status %s). Please try again.", status
            ))
        else:
            _logger.warning(
                "Received data with invalid payment status (%s) for transaction with reference %s.",
                status, self.reference,
            )
            self._set_error("Snippe: " + _("Unknown payment status: %s", status))
