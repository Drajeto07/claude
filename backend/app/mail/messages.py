"""What the app's e-mails say. Plain text: every mail program shows it, and nothing in
it loads from elsewhere (which would tell a tracker the message was opened)."""

from app.mail.sender import EmailMessage


def password_reset(to: str, link: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        kind="password_reset",
        subject="Reset your SmartDoc password",
        text=(
            "Someone asked to reset the password of your SmartDoc account. If it was you, open this link "
            "within the hour to choose a new one:\n\n"
            f"{link}\n\n"
            "The link works once. If it wasn't you, you can ignore this message: your password stays as it is.\n"
        ),
    )


def email_verification(to: str, link: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        kind="email_verification",
        subject="Confirm your e-mail address for SmartDoc",
        text=(
            "Confirm that this is your address, so SmartDoc can reach you about your account -- a forgotten "
            "password, for one. Open this link within two days:\n\n"
            f"{link}\n\n"
            "If you didn't sign up for SmartDoc, you can ignore this message.\n"
        ),
    )


def account_deleted(to: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        kind="account_deleted",
        subject="Your SmartDoc account is deleted",
        text=(
            "Your SmartDoc account and everything in it -- documents, their versions and pictures, templates "
            "and exports -- have been deleted, as you asked. This was the last e-mail SmartDoc will send you.\n"
        ),
    )


def password_changed(to: str, forgot_link: str, *, kept_one: bool = False) -> EmailMessage:
    """`kept_one`: the browser it was changed in stays signed in (a change, not a reset)."""
    signed_out = "every other browser signed in to it was signed out" if kept_one else "every browser signed in to it was signed out"
    return EmailMessage(
        to=to,
        kind="password_changed",
        subject="Your SmartDoc password was changed",
        text=(
            f"The password of your SmartDoc account was just changed, and {signed_out}.\n\n"
            "If you didn't do this, choose a new password at once:\n\n"
            f"{forgot_link}\n"
        ),
    )
