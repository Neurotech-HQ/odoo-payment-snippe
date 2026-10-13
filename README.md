# Snippe for Odoo

`payment_snippe` makes Snippe an Odoo payment provider. Customers pay invoices and sales
orders by mobile money (M-Pesa, Airtel Money, Mixx by Yas, HaloPesa) or card, and Odoo
registers the payment, reconciles the invoice and confirms the order by itself.

Built for Odoo 18. It needs Odoo.sh or a self-hosted Odoo: Odoo Online cannot install
custom modules.

## How customers pay

**By link (smartphone).** Odoo's own *Generate payment link* and the portal's *Pay now* open
Snippe's payment page. The customer pays there and comes back to Odoo's payment status page.

**By PIN prompt (any phone).** On a posted invoice in TZS, *Request mobile money payment*
sends a mobile money PIN prompt to the customer's phone. No browser or link is needed. If the
prompt is missed, press the button again.

Either way, Snippe tells Odoo through a signed webhook. Odoo checks the signature, then asks
Snippe for the payment and only acts if it names the same Odoo transaction, amount and
currency. A transaction marked done is then registered, reconciled and confirmed by Odoo's
standard post-processing.

## Set up

1. Add this repository to the Odoo addons path and install **Payment Provider: Snippe**.
2. In Snippe's dashboard, under Developers:
   - create an API key with the `collection` scope;
   - copy the webhook secret from Developers > Settings.
3. In Odoo, open Accounting > Configuration > Payment Providers > Snippe (on Community,
   Invoicing > Configuration > Online Payments > Payment Providers > Snippe):
   - paste the API key and the webhook secret;
   - pick the journal payments go to (a dedicated Snippe journal is recommended);
   - set the state to *Enabled*, or *Test* to try it first.
4. Make sure Odoo is reachable from the internet over HTTPS: Snippe delivers webhooks to
   `https://<your odoo>/payment/snippe/webhook`. The module sends this address with every
   payment; nothing has to be set in Snippe.

## What to know

- **Shillings only.** Snippe collects TZS in whole shillings, at least TZS 500; an amount with
  cents or below the minimum is refused.
- **Phone numbers.** A PIN prompt goes to a Tanzanian mobile number, typed as `0712345678` or
  `+255712345678`; it is sent to Snippe as `255712345678`.
- **References.** Every payment carries Odoo's transaction reference (for example
  `INV/2026/00123-1`) as `metadata.odoo_reference` and as the `Idempotency-Key`, so a retried
  request is never a second charge. Snippe's own payment reference is stored as the
  transaction's provider reference.
- **Paid.** An invoice first shows *In Payment*, then *Paid* once the bank statement line for
  Snippe's settlement is reconciled.
- **Customer email.** Snippe asks for an email with every PIN prompt. The customer's is used,
  else the company's.
- **Not yet.** Refunds through Odoo, saved cards and automatic fee entries.

## Run locally

`docker-compose.yml` runs Odoo 18 Community and PostgreSQL with this module mounted:

```sh
docker compose up -d
docker compose run --rm odoo odoo -c /etc/odoo/odoo.conf -d snippe -i payment_snippe \
  --stop-after-init
docker compose restart odoo
```

Odoo is then at http://localhost:8069 (`admin` / `admin`). To receive Snippe's webhooks, expose
it over HTTPS, for example with `cloudflared tunnel --url http://localhost:8069`, then set the
`web.base.url` system parameter to the tunnel's address and `web.base.url.freeze` to `True`
(Settings > Technical > System Parameters, in developer mode). Odoo builds the webhook URL from
`web.base.url`, and a tunnel that sends no `X-Forwarded-Host` leaves it on plain HTTP.

After changing the module, update it with `-u payment_snippe` in place of `-i`.

## Develop

Run the tests against an Odoo 18 checkout:

```sh
odoo-bin --addons-path=<odoo>/addons,<this repo> -d snippe_test \
  -i payment_snippe --test-enable --test-tags /payment_snippe --stop-after-init
```
