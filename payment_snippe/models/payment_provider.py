import logging
import pprint

import requests
from werkzeug.urls import url_join

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.const import REPORT_REASONS_MAPPING
from odoo.addons.payment_snippe import const


_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('snippe', "Snippe")], ondelete={'snippe': 'set default'}
    )
    snippe_api_key = fields.Char(
        string="Snippe API Key",
        help="A key from the Snippe dashboard, under Developers > API keys, with the collection"
             " scope.",
        required_if_provider='snippe',
        groups='base.group_system',
    )
    snippe_webhook_secret = fields.Char(
        string="Snippe Webhook Secret",
        help="From the Snippe dashboard, under Developers > Settings. It proves a webhook came"
             " from Snippe.",
        required_if_provider='snippe',
        groups='base.group_system',
    )
    snippe_api_url = fields.Char(
        string="Snippe API URL",
        default=const.API_URL,
        required_if_provider='snippe',
        groups='base.group_system',
    )

    # === BUSINESS METHODS === #

    @api.model
    def _get_compatible_providers(self, *args, is_validation=False, report=None, **kwargs):
        """ Override of `payment` to leave Snippe out of validations, which it cannot do. """
        providers = super()._get_compatible_providers(
            *args, is_validation=is_validation, report=report, **kwargs
        )
        if is_validation:
            unfiltered_providers = providers
            providers = providers.filtered(lambda p: p.code != 'snippe')
            payment_utils.add_to_report(
                report,
                unfiltered_providers - providers,
                available=False,
                reason=REPORT_REASONS_MAPPING['validation_not_supported'],
            )
        return providers

    def _get_supported_currencies(self):
        """ Override of `payment` to return the supported currencies. """
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'snippe':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'snippe':
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _snippe_make_request(self, endpoint, payload=None, method='POST', idempotency_key=None):
        """ Call the Snippe API and return the `data` of its answer.

        Note: self.ensure_one()

        :param str endpoint: The path, such as `/api/v1/sessions`.
        :param dict payload: The JSON body, or the query for a GET.
        :param str method: The HTTP method.
        :param str idempotency_key: Sent as `Idempotency-Key`, so a retried request is not a second
                                    payment.
        :return: The `data` of the response.
        :rtype: dict
        :raise ValidationError: If Snippe cannot be reached or refuses the request.
        """
        self.ensure_one()

        url = url_join(self.snippe_api_url or const.API_URL, endpoint)
        headers = {'Authorization': f'Bearer {self.snippe_api_key}'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        try:
            if method == 'GET':
                response = requests.get(url, params=payload, headers=headers, timeout=20)
            else:
                response = requests.post(url, json=payload, headers=headers, timeout=20)
        except requests.exceptions.RequestException as error:
            _logger.exception("Unable to reach endpoint at %s", url)
            raise ValidationError(
                "Snippe: " + _("Could not establish the connection to the API.")
            ) from error

        try:
            content = response.json()
        except ValueError:
            content = {}
        if not response.ok:
            _logger.error(
                "Snippe refused a request to %s (%s) with data:\n%s\nanswer:\n%s",
                url, response.status_code, pprint.pformat(payload), pprint.pformat(content),
            )
            raise ValidationError("Snippe: " + _(
                "Snippe refused the request: %s", content.get('message') or response.reason,
            ))
        return content.get('data', content)
