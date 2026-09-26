"""SMTP backend that reads its settings (host, app password, ...) from the encrypted 'smtp' integration."""

import smtplib

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

from apps.core.integrations import get_config


class EmailNotConfigured(Exception):
    pass


def smtp_kwargs(cfg):
    return {
        "host": cfg.get("host") or "smtp.gmail.com",
        "port": int(cfg.get("port") or 587),
        "username": cfg.get("username", ""),
        "password": cfg.get("password", ""),
        "use_tls": (cfg.get("use_tls") or "yes") == "yes",
        "timeout": 20,
    }


def from_address(cfg):
    email = cfg.get("from_email") or cfg.get("username")
    name = (cfg.get("from_name") or "Rasiko").replace('"', "")
    return f'"{name}" <{email}>'


class DashboardSMTPBackend(SMTPBackend):
    def __init__(self, fail_silently=False, **kwargs):
        cfg = get_config("smtp")
        if not cfg:
            raise EmailNotConfigured("Email (SMTP) is switched off in Settings -> Integrations.")
        kwargs = {**smtp_kwargs(cfg), **kwargs}
        super().__init__(fail_silently=fail_silently, **kwargs)


def test_connection(config):
    kw = smtp_kwargs(config)
    with smtplib.SMTP(kw["host"], kw["port"], timeout=15) as s:
        if kw["use_tls"]:
            s.starttls()
        s.login(kw["username"], kw["password"])
    return True, "Signed in to the email server. Use 'Send test email' to check delivery."
