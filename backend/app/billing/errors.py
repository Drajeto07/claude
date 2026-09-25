"""What a billing request can run into. Each says how the API answers it (one
handler in app/main.py), and its message is written for the user."""


class BillingError(Exception):
    status = 400
    code = "billing_error"


class BillingNotConfiguredError(BillingError):
    """No Stripe secret key: plans are enforced, but nobody can subscribe yet."""

    status, code = 503, "billing_not_configured"


class PlanNotAvailableError(BillingError):
    """Not a paid plan, or one without a Stripe price set up."""

    status, code = 400, "plan_not_available"


class AlreadySubscribedError(BillingError):
    """A second subscription would bill twice: plan changes go through the billing portal."""

    status, code = 409, "already_subscribed"


class NoBillingAccountError(BillingError):
    """The billing portal needs a Stripe customer, which only a checkout creates."""

    status, code = 409, "no_billing_account"


class BillingProviderError(BillingError):
    """Stripe refused the call or couldn't be reached (logged with the request id)."""

    status, code = 502, "billing_provider_error"


class InvalidWebhookError(BillingError):
    """A webhook whose Stripe signature doesn't check out: never acted on."""

    status, code = 400, "invalid_webhook"
