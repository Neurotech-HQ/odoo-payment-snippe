from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.payment_snippe import const
from odoo.addons.payment_snippe.controllers.main import SnippeController
from odoo.addons.payment_snippe.tests.common import SnippeCommon


REQUEST = 'odoo.addons.payment_snippe.models.payment_provider.PaymentProvider._snippe_make_request'


@tagged('post_install', '-at_install')
class TestPaymentTransaction(SnippeCommon):

    def test_payment_link_carries_the_odoo_reference(self):
        tx = self._create_transaction('redirect')
        session = {
            'reference': 'PAY1760000000001234',
            'payment_link_url': 'https://snippe.me/p/k3h6qa',
            'checkout_url': 'https://snippe.me/checkout/abc',
        }
        with patch(REQUEST, return_value=session) as request:
            values = tx._get_specific_rendering_values(None)

        self.assertEqual(values['api_url'], 'https://snippe.me/p/k3h6qa')
        self.assertEqual(tx.snippe_session_reference, 'PAY1760000000001234')
        endpoint = request.call_args.args[0]
        payload = request.call_args.kwargs['payload']
        self.assertEqual(endpoint, '/api/v1/sessions')
        self.assertEqual(request.call_args.kwargs['idempotency_key'], tx.reference)
        self.assertEqual(payload['amount'], 15000)
        self.assertEqual(payload['currency'], 'TZS')
        self.assertEqual(payload['allowed_methods'], ['mobile_money'])
        self.assertEqual(payload['metadata'], {'odoo_reference': tx.reference})
        self.assertTrue(payload['webhook_url'].endswith('/payment/snippe/webhook'))
        self.assertIn('reference=', payload['redirect_url'])
        self.assertNotIn('phone', payload['customer'])

    def test_cents_are_refused(self):
        tx = self._create_transaction('redirect', amount=15000.5)
        with patch(REQUEST) as request, self.assertRaises(UserError):
            tx._get_specific_rendering_values(None)
        request.assert_not_called()

    def test_less_than_the_minimum_is_refused(self):
        tx = self._create_transaction('redirect', amount=const.MINIMUM_AMOUNT - 1)
        with patch(REQUEST) as request, self.assertRaises(UserError):
            tx._get_specific_rendering_values(None)
        request.assert_not_called()

    def test_a_long_reference_gets_a_short_idempotency_key(self):
        short_tx = self._create_transaction('redirect')
        self.assertEqual(short_tx._snippe_idempotency_key(), short_tx.reference)
        long_tx = self._create_transaction('redirect', reference='S' * 40)
        key = long_tx._snippe_idempotency_key()
        self.assertEqual(len(key), const.IDEMPOTENCY_KEY_MAX_LENGTH)
        self.assertNotEqual(key, short_tx._snippe_idempotency_key())

    def test_completed_payment_marks_the_transaction_done(self):
        tx = self._create_transaction('redirect')
        with patch(REQUEST, return_value=self._snippe_payment('completed')) as request:
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.provider_reference, 'SN1760000000001234')
        self.assertEqual(request.call_args.args[0], '/v1/payments/SN1760000000001234')
        self.assertEqual(request.call_args.kwargs['method'], 'GET')

    def test_reads_the_older_api_version(self):
        tx = self._create_transaction('redirect')
        with patch(REQUEST, return_value=self._snippe_payment('completed', version='2026-01-01')):
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        self.assertEqual(tx.state, 'done')

    def test_each_status_sets_its_state(self):
        for status, state in (
            ('pending', 'pending'), ('ambiguous', 'pending'), ('failed', 'error'),
            ('voided', 'cancel'), ('expired', 'cancel'), ('cancelled', 'cancel'),
            ('reversed', 'error'),
        ):
            with self.subTest(status=status):
                tx = self._create_transaction('redirect', reference=f'{self.reference} {status}')
                payment = self._snippe_payment(status, reference=tx.reference)
                with patch(REQUEST, return_value=payment):
                    tx._handle_notification_data('snippe', {
                        'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
                    })
                self.assertEqual(tx.state, state)

    def test_a_failure_keeps_snippes_reason(self):
        tx = self._create_transaction('redirect')
        with patch(REQUEST, return_value=self._snippe_payment('failed')):
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        self.assertEqual(tx.state_message, 'Insufficient balance')

    def test_another_transactions_payment_is_refused(self):
        tx = self._create_transaction('redirect')
        with patch(REQUEST, return_value=self._snippe_payment(reference='INV/2026/99999-1')), \
                self.assertRaises(ValidationError):
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        self.assertEqual(tx.state, 'draft')

    def test_a_different_amount_is_refused(self):
        tx = self._create_transaction('redirect')
        with patch(REQUEST, return_value=self._snippe_payment(amount=100)), \
                self.assertRaises(ValidationError):
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        self.assertEqual(tx.state, 'draft')

    def test_unknown_reference_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env['payment.transaction']._get_tx_from_notification_data(
                'snippe', {'odoo_reference': 'nothing like this'}
            )

    def test_returning_customer_settles_a_failed_link_payment(self):
        """ A session whose payment failed reads as expired; its payment is still looked up. """
        tx = self._create_transaction('redirect', state='pending')
        tx.snippe_session_reference = 'PAY17600000000001234'
        answers = [
            {'status': 'expired', 'payment_intent_id': '8b91cfce-f831-4c1f-a528-e59b589947fd'},
            {'reference': 'SN1760000000001234'},
            self._snippe_payment('failed'),
        ]
        with patch(REQUEST, side_effect=answers) as request:
            SnippeController._check_on_checkout(tx)
        self.assertEqual(tx.state, 'error')
        self.assertEqual(request.call_args_list[1].args[0],
                         '/api/v1/payments/id/8b91cfce-f831-4c1f-a528-e59b589947fd')
