# Snippe for Odoo

Accept mobile money (M-Pesa, Airtel Money, Mixx by Yas, HaloPesa) and card payments in Odoo
through Snippe. Odoo registers each payment and reconciles the invoice automatically.

Requires Odoo 18 on Odoo.sh or self-hosted. Odoo Online cannot install custom modules.

## Features

- **Payment links.** *Generate payment link* and the portal's *Pay now* open Snippe's checkout.
- **PIN prompts.** *Request mobile money payment* on a posted TZS invoice sends a PIN prompt to
  the customer's phone.
- **Secure webhooks.** Signatures are verified and every payment is confirmed with Snippe
  before Odoo acts on it.

## Install

**Self-hosted:** add this repository to the Odoo addons path, then install
**Payment Provider: Snippe** from Apps.

**Odoo.sh:** add this repository as a submodule of your project, push, then install the module
from Apps. Test on a staging branch first; staging databases clear the Snippe keys, so enter
them again there.

To ship an update to Odoo.sh, bump `version` in `__manifest__.py` before pushing.

## Configure

1. In the Snippe dashboard, under Developers, create an API key with the `collection` scope and
   copy the webhook secret.
2. In Odoo, open the Snippe payment provider (Accounting, or Invoicing on Community >
   Configuration > Payment Providers), enter both keys, choose a journal and enable it.
3. Odoo must be reachable over HTTPS so Snippe can send webhooks.

## Notes

- TZS only, in whole shillings, minimum TZS 500.
- Phone numbers can be typed as `0712345678` or `+255712345678`.
- Refunds, saved cards and fee entries are not supported yet.

## Development

Run locally with Docker, then open http://localhost:8069, create a database and install the
module from Apps:

```sh
docker compose up -d
```

Run the tests:

```sh
odoo-bin --addons-path=<odoo>/addons,<this repo> -d snippe_test \
  -i payment_snippe --test-enable --test-tags /payment_snippe --stop-after-init
```
