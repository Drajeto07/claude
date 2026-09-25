"""Plans and billing (корекции.docx §35): a workspace has a plan, a plan grants
entitlements, and the backend enforces entitlements -- never a plan's name.
plans.json holds the plans; services/entitlements_service.py enforces them;
services/billing_service.py talks to Stripe."""
