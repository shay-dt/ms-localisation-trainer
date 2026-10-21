# auth_email.py
# ===========================================================================
# Sends the one-time sign-in code by email.
# Supports two providers — configure via Streamlit secrets:
#
#   EMAIL_PROVIDER = "gmail"   (default)  or  "resend"
#
#   For Gmail:
#     EMAIL_USER     = "you@gmail.com"
#     EMAIL_PASSWORD = "xxxx xxxx xxxx xxxx"   ← 16-char App Password
#     EMAIL_FROM     = "MS Trainer <you@gmail.com>"  (optional)
#
#   For Resend:
#     RESEND_API_KEY = "re_..."
#     EMAIL_FROM     = "MS Trainer <noreply@yourdomain.com>"
#
# Gmail App Password setup (2 min):
#   myaccount.google.com → Security → 2-Step Verification (enable) →
#   App passwords → create one called "MS Trainer" → copy the 16 chars.
# ===========================================================================

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


def _secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, os.environ.get(key, default)))
    except Exception:
        return os.environ.get(key, default)


def send_otp(to_email: str, code: str) -> bool:
    """Send the sign-in code. Returns True on success, False on failure."""
    provider = _secret("EMAIL_PROVIDER", "gmail").lower()
    if provider == "resend":
        return _send_via_resend(to_email, code)
    return _send_via_gmail(to_email, code)


def _email_html(code: str) -> str:
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:420px;margin:32px auto;
                padding:32px 28px;background:#fcfcfb;border:1px solid #e1e0d9;
                border-radius:12px;">
      <h2 style="margin:0 0 8px;color:#0a2633;font-size:20px;">🧠 MS Lesion Trainer</h2>
      <p style="color:#52514e;margin:0 0 24px;font-size:15px;">Your sign-in code is:</p>
      <div style="font-size:40px;font-weight:700;letter-spacing:12px;color:#2a78d6;
                  padding:16px;background:#eef3f7;border-radius:8px;text-align:center;">
        {code}
      </div>
      <p style="color:#898781;font-size:13px;margin:24px 0 0;">
        This code expires in 15 minutes.<br>
        If you didn't request this, you can safely ignore it.
      </p>
    </div>
    """


def _send_via_gmail(to_email: str, code: str) -> bool:
    host     = _secret("EMAIL_HOST",     "smtp.gmail.com")
    port     = int(_secret("EMAIL_PORT", "587"))
    user     = _secret("EMAIL_USER",     "")
    password = _secret("EMAIL_PASSWORD", "")
    from_    = _secret("EMAIL_FROM",     f"MS Trainer <{user}>")

    if not user or not password:
        st.error("Email not configured. Add EMAIL_USER and EMAIL_PASSWORD to Streamlit secrets.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your MS Trainer sign-in code"
    msg["From"]    = from_
    msg["To"]      = to_email
    msg.attach(MIMEText(_email_html(code), "html"))

    try:
        with smtplib.SMTP(host, port) as s:
            s.ehlo()
            s.starttls()
            s.login(user, password)
            s.sendmail(user, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Could not send email: {e}")
        return False


def _send_via_resend(to_email: str, code: str) -> bool:
    try:
        import resend  # pip install resend
        resend.api_key = _secret("RESEND_API_KEY", "")
        from_ = _secret("EMAIL_FROM", "MS Trainer <onboarding@resend.dev>")
        resend.Emails.send({
            "from":    from_,
            "to":      to_email,
            "subject": "Your MS Trainer sign-in code",
            "html":    _email_html(code),
        })
        return True
    except Exception as e:
        st.error(f"Resend error: {e}")
        return False
