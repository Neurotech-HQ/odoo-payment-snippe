# Snippe collects Tanzanian shillings, in whole shillings.
SUPPORTED_CURRENCIES = ['TZS']

# Snippe refuses a payment below this amount, in shillings.
MINIMUM_AMOUNT = 500

API_URL = 'https://api.snippe.sh'

# Snippe refuses an `Idempotency-Key` longer than this.
IDEMPOTENCY_KEY_MAX_LENGTH = 30

# Snippe payment statuses, as Odoo transaction states. An ambiguous payment's
# outcome is not known yet, so it stays pending until Snippe settles it.
PAYMENT_STATUS_MAPPING = {
    'pending': ('pending', 'ambiguous'),
    'done': ('completed',),
    'cancel': ('voided', 'expired', 'cancelled'),
    'error': ('failed', 'reversed'),
}

DEFAULT_PAYMENT_METHOD_CODES = {'snippe_mobile_money', 'card'}

# What Snippe's hosted page offers for each Odoo payment method.
ALLOWED_METHODS = {
    'snippe_mobile_money': ['mobile_money'],
    'card': ['card'],
}

# Only these events say what happened to a payment.
PAYMENT_EVENTS = (
    'payment.completed',
    'payment.failed',
    'payment.voided',
    'payment.expired',
    'payment.cancelled',
    'payment.reversed',
)

# A signed webhook older than this is refused, so a captured one cannot be replayed later.
WEBHOOK_TOLERANCE_SECONDS = 300

# How long a payment link stays payable.
SESSION_EXPIRES_IN = 24 * 60 * 60

# Snippe takes a Tanzanian mobile number as the country code followed by nine digits.
PHONE_COUNTRY_CODE = '255'
PHONE_PATTERN = r'255\d{9}'
