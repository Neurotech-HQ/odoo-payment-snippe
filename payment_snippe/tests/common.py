import hashlib
import hmac
import json
import time

from odoo.addons.account_payment.tests.common import AccountPaymentCommon


class SnippeCommon(AccountPaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.currency = cls.setup_other_currency('TZS')
        cls.amount = 15000.0
        cls.provider = cls._prepare_provider('snippe', update_values={
            'snippe_api_key': 'snp_' + '0' * 64,
            'snippe_webhook_secret': 'whsec_test',
        })
        cls.provider.journal_id = cls.company_data['default_journal_bank']
        cls.payment_method_id = cls.env.ref('payment_snippe.payment_method_snippe_mobile_money').id

    def _snippe_payment(
        self, status='completed', reference=None, amount=None, version='2026-01-25'
    ):
        """ A payment as Snippe's lookup returns it, in either API version. """
        payment = {
            'reference': 'SN1760000000001234',
            'status': status,
            'metadata': {'odoo_reference': reference or self.reference},
            'failure_reason': 'Insufficient balance' if status == 'failed' else '',
        }
        value = int(self.amount if amount is None else amount)
        if version == '2026-01-25':
            payment['amount'] = {'value': value, 'currency': 'TZS', 'asset_scale': 0}
        else:
            payment.update(amount=value, currency='TZS')
        return payment

    @staticmethod
    def _sign(body, secret='whsec_test', timestamp=None):
        """ Headers signing `body` as Snippe does: HMAC-SHA256 over `<timestamp>.<body>`. """
        timestamp = str(int(time.time()) if timestamp is None else timestamp)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256)
        return raw, {
            'Content-Type': 'application/json',
            'X-Webhook-Timestamp': timestamp,
            'X-Webhook-Signature': signature.hexdigest(),
        }
