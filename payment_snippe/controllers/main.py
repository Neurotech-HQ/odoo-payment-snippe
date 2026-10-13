import hashlib
import hmac
import json
import logging
import time

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.payment_snippe import const


_logger = logging.getLogger(__name__)


class SnippeController(http.Controller):
    _return_url = '/payment/snippe/return'
    _webhook_url = '/payment/snippe/webhook'

    @http.route(_return_url, type='http', methods=['GET'], auth='public')
    def snippe_return_from_checkout(self, reference=None, **_kwargs):
        """ Bring the customer back from Snippe's payment page to Odoo's status page.

        The webhook settles the transaction; this only checks on it, so a customer who returns
        before the webhook arrives already sees the outcome.

        :param str reference: The Odoo reference of the transaction.
        """
        if reference:
            tx_sudo = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference), ('provider_code', '=', 'snippe'),
            ], limit=1)
            if tx_sudo and tx_sudo.state in ('draft', 'pending'):
                self._check_on_checkout(tx_sudo)
        return request.redirect('/payment/status')

    @staticmethod
    def _check_on_checkout(tx_sudo):
        """ Settle a transaction from its payment link, if the customer tried to pay there.

        The session names the payment the customer made on it, whatever its outcome; a session
        whose payment failed is reported as expired, so its status is not relied upon.

        :param recordset tx_sudo: The transaction, as a sudoed `payment.transaction` record.
        """
        if not tx_sudo.snippe_session_reference:
            return
        try:
            session = tx_sudo.provider_id._snippe_make_request(
                f'/api/v1/sessions/{tx_sudo.snippe_session_reference}', method='GET'
            )
            intent_id = session.get('payment_intent_id')
            if not intent_id:
                return
            payment = tx_sudo.provider_id._snippe_make_request(
                f'/api/v1/payments/id/{intent_id}', method='GET'
            )
            if payment.get('reference'):
                tx_sudo._handle_notification_data('snippe', {
                    'odoo_reference': tx_sudo.reference, 'reference': payment['reference'],
                })
        except UserError:
            _logger.exception("Unable to check on transaction %s; the webhook will settle it",
                              tx_sudo.reference)

    @http.route(_webhook_url, type='http', methods=['POST'], auth='public', csrf=False)
    def snippe_webhook(self):
        """ Process a payment event Snippe sent to the webhook.

        :return: An empty answer, to acknowledge the event.
        """
        raw_body = request.httprequest.get_data()
        try:
            event = json.loads(raw_body)
        except ValueError:
            _logger.warning("Received a webhook that is not JSON.")
            return request.make_json_response('', status=400)

        event_type = event.get('type') or event.get('event')
        if event_type not in const.PAYMENT_EVENTS:
            return request.make_json_response('')

        # 2026-01-25 puts the payment under `data`; 2026-01-01 sends it flat.
        data = event.get('data') if isinstance(event.get('data'), dict) else event
        notification_data = {
            'reference': data.get('reference'),
            'odoo_reference': (data.get('metadata') or {}).get('odoo_reference'),
        }
        _logger.info("Notification %s received from Snippe for %s", event_type, notification_data)
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'snippe', notification_data
            )
            self._verify_notification_signature(
                raw_body,
                request.httprequest.headers.get('X-Webhook-Signature'),
                request.httprequest.headers.get('X-Webhook-Timestamp'),
                tx_sudo,
            )
            tx_sudo._handle_notification_data('snippe', notification_data)
        except ValidationError:  # Acknowledge the notification to avoid getting spammed.
            _logger.exception("Unable to handle the notification data; skipping to acknowledge")
        return request.make_json_response('')

    @staticmethod
    def _verify_notification_signature(raw_body, signature, timestamp, tx_sudo):
        """ Check that Snippe signed the body, recently, with the provider's webhook secret.

        Snippe signs `<timestamp>.<body>` with HMAC-SHA256 and sends the hex digest.

        :param bytes raw_body: The body as received.
        :param str signature: The `X-Webhook-Signature` header.
        :param str timestamp: The `X-Webhook-Timestamp` header, in Unix seconds.
        :param recordset tx_sudo: The transaction the event names.
        :raise Forbidden: If the signature is missing, stale or wrong.
        """
        if not signature or not timestamp:
            _logger.warning("Received notification with missing signature.")
            raise Forbidden()
        try:
            age = abs(time.time() - int(timestamp))
        except ValueError:
            _logger.warning("Received notification with an unreadable timestamp.")
            raise Forbidden() from None
        if age > const.WEBHOOK_TOLERANCE_SECONDS:
            _logger.warning("Received notification signed %d seconds ago.", age)
            raise Forbidden()

        secret = (tx_sudo.provider_id.snippe_webhook_secret or '').encode()
        expected = hmac.new(
            secret, timestamp.encode() + b'.' + raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            _logger.warning("Received notification with invalid signature.")
            raise Forbidden()
