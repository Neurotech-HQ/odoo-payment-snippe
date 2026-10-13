from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.payment_snippe.tests.common import SnippeCommon


REQUEST = 'odoo.addons.payment_snippe.models.payment_provider.PaymentProvider._snippe_make_request'


@tagged('post_install', '-at_install')
class TestPushWizard(SnippeCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner.write({'phone': '+255712345678', 'email': 'neema@example.com'})
        cls.tzs_invoice = cls.init_invoice(
            'out_invoice', partner=cls.partner, amounts=[15000.0], currency=cls.currency, post=True,
        )

    def _wizard(self, **values):
        return self.env['payment.snippe.push.wizard'].create({
            'move_id': self.tzs_invoice.id, **values,
        })

    def test_the_invoice_offers_the_prompt(self):
        self.assertTrue(self.tzs_invoice.snippe_can_request_payment)
        self.provider.state = 'disabled'
        self.tzs_invoice.invalidate_recordset(['snippe_can_request_payment'])
        self.assertFalse(self.tzs_invoice.snippe_can_request_payment)

    def test_prompt_creates_a_pending_transaction_on_the_invoice(self):
        wizard = self._wizard()
        self.assertEqual(wizard.phone, '+255712345678')
        self.assertEqual(wizard.amount, self.tzs_invoice.amount_residual)
        with patch(REQUEST, return_value={'reference': 'SN1760000000001234'}) as request:
            wizard.action_send()

        tx = self.tzs_invoice.transaction_ids
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx.state, 'pending')
        self.assertEqual(tx.provider_reference, 'SN1760000000001234')
        self.assertEqual(request.call_args.args[0], '/v1/payments')
        payload = request.call_args.kwargs['payload']
        self.assertEqual(request.call_args.kwargs['idempotency_key'], tx.reference)
        self.assertEqual(payload['phone_number'], '255712345678')
        self.assertEqual(payload['details'], {'amount': int(self.tzs_invoice.amount_residual),
                                              'currency': 'TZS'})
        self.assertEqual(payload['customer']['email'], 'neema@example.com')
        self.assertEqual(payload['metadata'], {'odoo_reference': tx.reference})

    def test_paid_prompt_registers_and_reconciles_the_payment(self):
        with patch(REQUEST, return_value={'reference': 'SN1760000000001234'}):
            self._wizard().action_send()
        tx = self.tzs_invoice.transaction_ids
        lookup = self._snippe_payment('completed', reference=tx.reference,
                                      amount=self.tzs_invoice.amount_residual)
        with patch(REQUEST, return_value=lookup):
            tx._handle_notification_data('snippe', {
                'odoo_reference': tx.reference, 'reference': 'SN1760000000001234',
            })
        tx._post_process()

        self.assertEqual(tx.state, 'done')
        self.assertTrue(tx.payment_id)
        self.assertIn(self.tzs_invoice.payment_state, ('in_payment', 'paid'))

    def test_more_than_owed_is_refused(self):
        wizard = self._wizard(amount=self.tzs_invoice.amount_residual + 1)
        with patch(REQUEST) as request, self.assertRaises(UserError):
            wizard.action_send()
        request.assert_not_called()

    def test_a_customer_without_email_uses_the_companys(self):
        self.partner.email = False
        self.env.company.email = 'finance@reliance.example'
        with patch(REQUEST, return_value={'reference': 'SN1'}) as request:
            self._wizard().action_send()
        self.assertEqual(request.call_args.kwargs['payload']['customer']['email'],
                         'finance@reliance.example')

    def test_phone_numbers_are_normalized(self):
        normalize = self.env['payment.snippe.push.wizard']._normalize_phone
        for typed in ('0712 345 678', '+255 712-345-678', '00255712345678', '255712345678'):
            with self.subTest(phone=typed):
                self.assertEqual(normalize(typed), '255712345678')
        for typed in ('712345678', '+254712345678', '07123456', 'not a phone'):
            with self.subTest(phone=typed), self.assertRaises(UserError):
                normalize(typed)

    def test_a_wrong_phone_sends_nothing(self):
        wizard = self._wizard(phone='12345')
        with patch(REQUEST) as request, self.assertRaises(UserError):
            wizard.action_send()
        request.assert_not_called()
        self.assertFalse(self.tzs_invoice.transaction_ids)
