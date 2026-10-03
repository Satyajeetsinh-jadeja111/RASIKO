# Rasiko: secrets and API keys

This file lists every key Rasiko uses: where you get it and where you enter it.
**It holds no actual keys.** Never write real keys here, in the chat, or in the code repository.

## How it works

- Every paid or keyed service is built into the site but is **OFF by default**.
- To switch one on: Dashboard → **Settings → Integrations** → turn on the toggle → paste the keys → **Test connection** → Save.
- Keys are stored encrypted. After saving, the dashboard only shows `•••• last 4`. To change a key, paste a new one.
- Only the **Owner** role can see or change this page. Every change is written to the audit log, and a security email is sent to the admin.
- While a service is off, the site uses the free fallback listed below, so nothing breaks.

## A. Keys you add from the dashboard (Settings → Integrations)

| Service | Paid? | Keys to paste | Where to get them | Free fallback while OFF |
|---|---|---|---|---|
| **WhatsApp Business (Meta Cloud API)** | Yes. Setup is free, but Meta charges for most messages the business starts (order updates, offers). Check Meta's current India rates. | Phone number ID, permanent access token, WhatsApp Business Account ID, webhook verify token (you make this up), approved template names | Meta for Developers → your app → WhatsApp → API Setup; Meta Business Manager for the permanent token and templates | Free "Order on WhatsApp" click-to-chat link to the shop's number. Order updates go by email only |
| **Razorpay** (UPI, cards, netbanking, wallets) | Per-transaction fee, no monthly fee | Key ID, key secret, webhook secret | Razorpay Dashboard → Account & Settings → API Keys; Webhooks section for the secret | Online payment is hidden; Cash on Delivery only |
| **Stripe** | Per-transaction fee. India accounts are invite-only | Publishable key, secret key, webhook signing secret | Stripe Dashboard → Developers → API keys; Developers → Webhooks | Hidden at checkout |
| **Claude AI help chat** | Pay per use | API key, model name (a fast, low-cost model is filled in by default) | console.anthropic.com → API Keys | FAQ-matching help bot answers from your Help Center articles |
| **SMS OTP** (MSG91, Twilio, etc.) | Pay per SMS. Indian SMS also needs DLT registration | Provider, API key/auth token, sender ID, DLT template ID | Your SMS provider's dashboard | The Cash on Delivery phone check uses an email OTP |
| **Email (SMTP)** | Free with Gmail (sending limits apply) | SMTP host (smtp.gmail.com), port (587), TLS on, email address, **app password**, sender name, admin email address(es) | Google Account → Security → 2-Step Verification → App passwords | Emails are saved in the email log but not sent |
| **Cloud storage (S3-compatible)**, optional | Paid by storage used | Endpoint URL, bucket name, access key, secret key, region | Your storage provider (AWS S3, Cloudflare R2, DigitalOcean Spaces…) | Images are stored on the server itself |

Payment gateway rule: only one online gateway is active at a time. Until Stripe approves you, the recommended default is **Razorpay**.

## B. Business details (Dashboard → Settings → Store), not secret

FSSAI licence number · GSTIN · shop address and phone · store location pin on the map · delivery radius and allowed Rajkot pincodes (a starter list will be seeded, **please verify it**) · opening hours and holidays · shop WhatsApp number for the click-to-chat link.

## C. Secrets that must stay in the server's `.env` file

These can't go in the dashboard, because the site needs them before the dashboard can start.
The build ships an `.env.example` file that explains each one. Set the values once on the server.

| Variable | What it is | How to make it |
|---|---|---|
| `DJANGO_SECRET_KEY` | Signs logins and sessions | A long random string (the README gives a one-line command) |
| `FIELD_ENCRYPTION_KEY` | Encrypts every key you save in the dashboard. **If lost, all saved keys must be re-entered.** Back it up somewhere safe. | A Fernet key (the README gives a one-line command) |
| `POSTGRES_PASSWORD` | Database password | Any strong password |
| `REDIS_PASSWORD` | Cache/queue password | Any strong password |
| `ALLOWED_HOSTS`, `SITE_URL` | Your domain | e.g. `rasiko.in` |
| `ADMIN_URL` | The secret dashboard address | e.g. `manage-7k2p/` |
| `OWNER_EMAIL`, `OWNER_PASSWORD` | Creates the first Owner account (change the password after the first login) | You choose |

## D. Safety rules

- Don't share keys in chat, email or screenshots. Paste them only into the dashboard.
- Turn on 2FA for the Owner account before adding any payment keys.
- If a key is ever exposed, revoke it at the provider and paste a new one in the dashboard.
- Use **test/sandbox keys** first (Razorpay test mode, Stripe test mode), then switch to live keys.
