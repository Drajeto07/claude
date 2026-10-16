# PLAN-004: Stripe flows, every path and webhook ordering

Branch `cloud/plan-004-stripe-flows`, from `feature/smartdoc-production-hardening` at `8966ec7` (Alembic head `b8534d3c4256`).

## Summary

Every Stripe flow was walked against the code and the existing stand-in for Stripe's API (`OfflineStripe`, `backend/tests/test_billing.py`): checkout, the customer portal, upgrade, downgrade, cancel at period end, cancel at once, renewal, a failed payment through `past_due` and `unpaid` and back, refunds and disputes, and webhooks arriving twice, late, out of order or at the same moment. The design was already sound where it counted (the subscription is fetched from Stripe instead of taken from the event, the signature is checked first), and the review found these gaps, each fixed with a test that fails without the fix:

1. **A signed body that is no Stripe event crashed** (`500`, an `AttributeError`) for `[]`, `null`, a string, `{}`, an event without `data`, with `data.object` a string, null or list, without an id, with a numeric type. It now answers `400 invalid_webhook` with the same words as a bad signature (14 bodies tested).
2. **An event naming a subscription in an odd shape crashed** (`"subscription": ["x"]` made `_id` fail). Now acknowledged and ignored.
3. **A subscription Stripe no longer has** (`resource_missing`) answered `502`, so Stripe would retry for three days to no end. Now `200`; Stripe being unreachable still answers `502` (retry wanted).
4. **Two webhooks handled at the same moment could write in the wrong order**, because each reads Stripe and the older read can be written last; and two first events for one workspace (a checkout's two events arrive together) could both insert the row (unique violation, `500`). Fixed with the workspace hold the plan checks use (`hold_workspace`) plus `subscriptions.stripe_synced_at`: a read older than the stored one is dropped. **Migration `d41f7a60c9e2`.**
5. **The signature check now stands on its own.** (Not a gap: Stripe's own `construct_event` already refused a request signed more than five minutes ago, but nothing tested it.) The gateway checks the signature itself on the raw bytes with that tolerance, then parses and validates the body, which is what makes fix 1 possible; a replay an hour later is tested and refused.
6. **Payment failures, refunds and disputes were invisible** (ignored without a trace). They are now audit-logged (`billing.payment_failed`, `billing.charge_refunded`, `billing.dispute`) so the owner can act in Stripe. They change no plan: ending a subscription over them is the owner's decision in Stripe and arrives as `customer.subscription.deleted`. The invoice's subscription is read in both API shapes (`subscription`, and `parent.subscription_details.subscription` since 2025-03-31).
7. **Two live subscriptions on one workspace** (two checkouts opened together, both paid) silently left one billing with no trace. Now audited as `billing.duplicate_subscription` and logged; cancelling the extra one is an owner action (see decisions).
8. `checkout.session.async_payment_succeeded` / `_failed` (delayed payment methods) are now handled like `checkout.session.completed`.

The table of every flow, the events it rests on, what the app does and the test that covers it is in `docs/billing/README.md`, which also lists the settings the owner needs in the Stripe dashboard.

## Files changed

- `backend/app/billing/stripe_gateway.py`: signature check on the raw bytes with tolerance; `parse_event` (validated shape); `_id` tolerates any shape; `subscription()` returns `None` for `resource_missing`; `invoice_subscription_id`.
- `backend/app/services/billing_service.py`: `handle` (noted events, async-payment events, missing subscription, read time taken before the fetch), `sync` (hold, read-time guard, duplicate audit), `_note`.
- `backend/app/db/models/billing.py`: `Subscription.stripe_synced_at`.
- `backend/alembic/versions/d41f7a60c9e2_subscriptions_stripe_synced_at.py`: new.
- `backend/tests/test_billing.py` (stand-in extended: events carry ids, Stripe can be unreachable or lack a subscription; 28 tests added), `backend/tests/test_billing_webhook_race.py` (new), `backend/tests/test_db_migration.py` (migration test).
- `docs/billing/README.md` (new), `README.md` (Stripe section: events, tests, migration), this report.

No API schema changed (the webhook route is not in the OpenAPI schema and `BillingOut` is the same), so nothing was regenerated.

## Design decisions

- **Idempotency by state, not by event id.** Every subscription event leads to a fresh read of Stripe and the same write, so repeating or reordering events changes nothing; a ledger of event ids would only save one fetch per duplicate and bring a table, a clean-up and a rule for events that failed half-way. The tests send the same event id twice and different ids in every order.
- **The read time, not the event time, orders writes.** A Stripe subscription has no "updated at"; an event's `created` says when something happened, not when it was read. The time taken just before the fetch is what a stored state is at least as fresh as. Server clocks of several instances could differ by milliseconds; the hold makes the window tiny anyway.
- **The hold goes first.** `hold_workspace` (an `UPDATE` that changes nothing: the row lock on PostgreSQL, the write lock on SQLite) is taken before anything is read, as its own docstring asks, and the row is then re-read (`populate_existing`) so a wait is never followed by a stale copy. For a subscription with no workspace id in its metadata (made in Stripe's dashboard) the row is found first and then held; that rare path can lose a race on SQLite only.
- **Refunds and disputes are recorded, not acted on.** The app can't know whether a refund means the customer should lose the plan; Stripe keeps the subscription going unless told otherwise. A lost dispute likewise. Acting automatically would be a business decision (and a `cancel` call to Stripe that nothing here makes).
- **A signed body that is no event is `400`, not `200`.** Stripe retries a `400` for three days, which is noise but also shows in the dashboard as a failing endpoint if Stripe's format ever changes; that visibility is wanted.

## Tests added

`backend/tests/test_billing.py` (51 tests in the file, 28 new): `test_a_downgrade_in_the_portal_changes_the_limits_and_deletes_nothing`, `test_cancelling_at_the_period_end_then_changing_ones_mind`, `test_a_renewal_moves_the_period_and_keeps_the_plan`, `test_a_failed_payment_runs_through_past_due_and_unpaid_and_back_to_active`, `test_a_failed_payment_names_its_subscription_in_either_api_version`, `test_a_workspace_with_an_unpaid_subscription_can_subscribe_again`, `test_a_paused_subscription_gives_no_plan_until_it_is_resumed`, `test_a_checkout_that_is_not_paid_yet_gives_no_plan`, `test_a_delayed_payment_method_settling_after_the_checkout_gives_the_plan`, `test_a_refund_or_a_dispute_is_recorded_and_changes_no_plan`, `test_a_price_that_is_no_plans_goes_by_the_subscriptions_plan_or_changes_nothing`, `test_the_same_event_delivered_twice_changes_nothing_the_second_time`, `test_a_subscription_update_before_the_checkout_completed_event_is_the_same_as_after`, `test_a_late_event_does_not_bring_back_a_subscription_that_has_ended`, `test_two_live_subscriptions_are_audited_and_the_newer_one_is_followed`, `test_an_older_read_of_a_subscription_never_overwrites_a_newer_one`, `test_a_webhook_for_a_subscription_stripe_no_longer_has_is_acknowledged`, `test_a_webhook_while_stripe_cant_be_reached_is_refused_so_stripe_sends_it_again`, `test_a_signed_body_that_is_no_event_is_refused_without_a_crash_or_a_trace` (14 bodies), `test_events_that_name_no_subscription_in_any_shape_are_acknowledged`, `test_a_webhook_signed_long_ago_is_refused`, `test_a_refused_webhook_says_nothing_about_why`, `test_webhooks_without_a_webhook_secret_are_refused_not_trusted`, `test_a_webhook_on_a_server_without_stripe_is_answered_not_crashed`, `test_the_real_gateway_maps_stripes_answers`; `test_events_about_nothing_here_are_acknowledged_and_ignored` was made stricter (a one-off payment that names a subscription).
`backend/tests/test_billing_webhook_race.py`: `test_two_first_events_make_one_row_and_the_later_read_wins` (both orders; SQLite file with two connections, and PostgreSQL when `SMARTDOC_TEST_POSTGRES_URL` is set, which CI's `-m postgres` step does).
`backend/tests/test_db_migration.py`: `test_the_stripe_synced_at_migration_keeps_subscriptions_and_downgrades`.

Written before the fix: with the app code at the base and the new tests in place, 21 failed (all the fixes above) and 30 passed (the existing tests, and the new ones for behaviour that was already right: a late event after a cancellation, Stripe unreachable, a refused bad signature).

## Results

Full backend suite: `1949 passed, 6 skipped, 2 warnings in 439.87s` (`cd backend && /tmp/venv/bin/python -m pytest -q -p no:cacheprovider`; the skips are the PostgreSQL-only tests, which run in CI). `tests/test_billing.py` 51 passed; `tests/test_billing_webhook_race.py` 2 passed, 2 skipped (PostgreSQL); `tests/test_db_migration.py` 7 passed. `python -m scripts.export_openapi` produces no diff (no schema change). Frontend untouched, so no Vitest or Playwright run. Commands: the pytest runs above, `scripts/mutate` runs described below (a throwaway script kept outside the repo), `python -m scripts.export_openapi`.

## Mutation checks

Control run green (53 passed, 2 skipped), then each break on its own, the tests run, restored:

| Break | Failing test |
| --- | --- |
| `hold_workspace` removed from `sync` | `test_billing_webhook_race.py::test_two_first_events_make_one_row_and_the_later_read_wins[sqlite-...]` |
| stale-read guard (`stripe_synced_at > read_at`) off | `test_an_older_read_of_a_subscription_never_overwrites_a_newer_one` |
| "replaced and not live: ignore" off | `test_late_news_about_a_replaced_subscription_is_ignored` |
| duplicate-subscription audit off | `test_two_live_subscriptions_are_audited_and_the_newer_one_is_followed` |
| noted events (payment failed, refund, dispute) off | `test_a_failed_payment_runs_through_past_due_and_unpaid_and_back_to_active` |
| checkout mode check off | first NOT caught (a payment-mode session with no subscription id was returned early anyway); the test now gives the session a subscription id, then `test_events_about_nothing_here_are_acknowledged_and_ignored` fails |
| missing subscription returns `None` ignored | `test_a_webhook_for_a_subscription_stripe_no_longer_has_is_acknowledged` |
| signature tolerance removed | `test_a_webhook_signed_long_ago_is_refused` |
| event shape check off | `test_a_signed_body_that_is_no_event_is_refused_without_a_crash_or_a_trace[...]` |
| `resource_missing` mapping off | `test_the_real_gateway_maps_stripes_answers` |
| `_id` accepts any shape | `test_events_that_name_no_subscription_in_any_shape_are_acknowledged` |
| invoice's new-style subscription path off | `test_a_failed_payment_names_its_subscription_in_either_api_version` |

## Migration

`d41f7a60c9e2` ("subscriptions stripe synced at"), `down_revision = b8534d3c4256`. Adds the nullable `subscriptions.stripe_synced_at` (timestamptz); the downgrade drops it. No table is made, so no RLS to add. Tested up/down/up on SQLite (`test_db_migration.py`, including a row from before). PostgreSQL: I was not given a database here, so it is not run locally; CI's migrations job (`alembic upgrade head`, `alembic check`, `alembic downgrade base`, `alembic upgrade head`, then `-m postgres`) covers it. **Other workers may add migrations on the same head `b8534d3c4256`; the owner re-parents this one (change `down_revision`, and the two revision ids pinned in `test_the_stripe_synced_at_migration_keeps_subscriptions_and_downgrades`).**

## Flows judged fine as they are

Checkout (workspace id on the session and the subscription, refused while a live subscription exists, customer reused), the portal (`409` without a customer), upgrade and downgrade by price with the metadata fallback, cancel at period end and at once, renewal through `customer.subscription.updated`, `past_due` keeping the plan while Stripe retries and `unpaid` giving the free plan, pause and resume, news about a replaced subscription, a dashboard-made subscription found by customer, the unlimited rate class for the webhook (a signature is what makes it trusted), the request-size limit already covering the webhook body.

## Needs the owner's Stripe dashboard

Listed in `docs/billing/README.md`: the webhook endpoint and its twelve events; Smart Retries and what happens when they run out (recommended: cancel the subscription, so the old one can't be paid later against a newer one); the portal's plan switching list, cancel option and return page; refunds and disputes (the app only records them); the real prices and limits (`plans.json` holds placeholders).

## Risks and open questions

- `past_due` keeps the plan for as long as Stripe retries (its Smart Retries default is about a week); that is the existing, deliberate grace. A shorter grace is a product decision.
- A subscription with several items is read by its first item.
- A portal cancellation with a `cancel_at` date that isn't the period's end shows the period end on the billing page.
- No reconciliation job: a missed webhook beyond Stripe's three days of retries is repaired by the subscription's next event or a re-send from the dashboard.
- The race test's PostgreSQL variants run only in CI (no local database was given).
- The webhook route is not in the OpenAPI schema (unchanged), so `test_security_suite.py::_REQUESTS` needed no new entry; no route was added.

## Decisions for the owner

1. **Two live subscriptions:** audit only (now), or cancel the older one in Stripe automatically (needs a cancel call in the gateway and a rule about refunds)?
2. **Refund or lost dispute:** keep the plan until cancelled in Stripe (now), or end the plan automatically?
3. **After the last payment retry:** "cancel the subscription" (recommended) or "mark unpaid" in Stripe's retry settings.
4. Whether to add a periodic reconciliation with Stripe (a job that lists active subscriptions and syncs them).

## Not done

PostgreSQL run of the migration and the race test (CI); a real checkout in Stripe's test mode (no Stripe account, by the task's rules).
