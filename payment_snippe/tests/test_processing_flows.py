import time
from unittest.mock import patch

from werkzeug.exceptions import Forbidden

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_snippe.controllers.main import SnippeController
from odoo.addons.payment_snippe.tests.common import SnippeCommon


HANDLE = (
    'odoo.addons.payment.models.payment_transaction.PaymentTransaction._handle_notification_data'
)


@tagged('post_install', '-at_install')
class TestProcessingFlows(SnippeCommon, PaymentHttpCommon):

    def _event(self, event_type='payment.completed', reference=None):
        return {
            'id': 'evt_0123456789abcdef01234567',
            'type': event_type,
            'api_version': '2026-01-25',
            'data': {
                'reference': 'SN1760000000001234',
                'status': 'completed',
                'metadata': {'odoo_reference': reference or self.reference},
            },
        }

    def _post(self, raw, headers):
        return self.url_open(self._build_url(SnippeController._webhook_url), data=raw,
                             headers=headers)

    @mute_logger('odoo.addons.payment_snippe.controllers.main')
    def test_signed_webhook_is_processed(self):
        self._create_transaction('redirect')
        raw, headers = self._sign(self._event())
        with patch(HANDLE) as handle:
            response = self._post(raw, headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(handle.call_count, 1)
        self.assertEqual(handle.call_args.args[1], {
            'reference': 'SN1760000000001234', 'odoo_reference': self.reference,
        })

    @mute_logger('odoo.addons.payment_snippe.controllers.main', 'werkzeug')
    def test_wrongly_signed_webhook_is_refused(self):
        self._create_transaction('redirect')
        raw, headers = self._sign(self._event(), secret='not the secret')
        with patch(HANDLE) as handle:
            response = self._post(raw, headers)
        self.assertEqual(response.status_code, 403)
        handle.assert_not_called()

    @mute_logger('odoo.addons.payment_snippe.controllers.main')
    def test_the_older_flat_payload_is_read(self):
        self._create_transaction('redirect')
        raw, headers = self._sign({
            'event': 'payment.completed',
            'reference': 'SN1760000000001234',
            'metadata': {'odoo_reference': self.reference},
        })
        with patch(HANDLE) as handle:
            self._post(raw, headers)
        self.assertEqual(handle.call_args.args[1]['odoo_reference'], self.reference)

    @mute_logger('odoo.addons.payment_snippe.controllers.main')
    def test_every_payment_outcome_is_processed(self):
        self._create_transaction('redirect')
        for event_type in ('payment.failed', 'payment.voided', 'payment.expired'):
            with self.subTest(event=event_type):
                raw, headers = self._sign(self._event(event_type))
                with patch(HANDLE) as handle:
                    self._post(raw, headers)
                self.assertEqual(handle.call_count, 1)

    @mute_logger('odoo.addons.payment_snippe.controllers.main')
    def test_other_events_are_acknowledged_and_ignored(self):
        raw, headers = self._sign({'type': 'payout.completed', 'data': {}})
        with patch(HANDLE) as handle:
            response = self._post(raw, headers)
        self.assertEqual(response.status_code, 200)
        handle.assert_not_called()

    def test_signature_checks(self):
        tx = self._create_transaction('redirect')
        raw, headers = self._sign(self._event())
        verify = SnippeController._verify_notification_signature
        signature, timestamp = headers['X-Webhook-Signature'], headers['X-Webhook-Timestamp']
        self._assert_does_not_raise(Forbidden, verify, raw, signature, timestamp, tx)
        with mute_logger('odoo.addons.payment_snippe.controllers.main'):
            self.assertRaises(Forbidden, verify, raw, None, timestamp, tx)
            self.assertRaises(Forbidden, verify, raw + b' ', signature, timestamp, tx)
            old_raw, old = self._sign(self._event(), timestamp=int(time.time()) - 3600)
            self.assertRaises(Forbidden, verify, old_raw, old['X-Webhook-Signature'],
                              old['X-Webhook-Timestamp'], tx)
