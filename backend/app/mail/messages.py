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


def password_changed(to: str, forgot_link: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        kind="password_changed",
        subject="Your SmartDoc password was changed",
        text=(
            "The password of your SmartDoc account was just changed, and every browser signed in to it was "
            "signed out.\n\n"
            "If you didn't do this, choose a new password at once:\n\n"
            f"{forgot_link}\n"
        ),
    )
