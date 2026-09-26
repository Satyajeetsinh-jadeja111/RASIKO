# Rasiko

Rasiko is an online cold-drinks and beverages shop for Rajkot, built with Django. Customers get a storefront in English, Gujarati and Hindi with checkout, delivery-area checks, live order tracking, reviews and 24×7 help chat. Staff get a dashboard for orders, stock, products, offers, delivery rules, analytics and settings.

Every paid or keyed service starts **off**. The Owner switches it on and pastes its keys in **Dashboard → Settings → Integrations**. Keys never go in `.env` or in the code.

| Service | While off, the shop uses |
|---|---|
| Razorpay (UPI, cards) | Cash on Delivery |
| Stripe (cards) | Cash on Delivery |
| WhatsApp Business | "Order on WhatsApp" link (free `wa.me`) |
| Claude AI help chat | FAQ search, then hand-off to a person |
| SMS OTP | Email codes |
| Email (SMTP) | Emails are logged as "not sent" in Dashboard → Email |
| S3 storage | Files on the server's disk |

## Stack

- Django 5.2 on Python 3.12, served by Uvicorn (ASGI, so the dashboard's live order alerts work over WebSockets)
- PostgreSQL 16, with its full-text search for products and help articles
- Redis for the cache, Celery and Channels
- Celery worker plus Celery beat for scheduled jobs: releasing unpaid stock holds, subscriptions, daily and weekly summaries, birthday coins
- htmx, Chart.js and Leaflet, all served from `static/vendor` (no external CDNs)
- Tailwind build in `frontend/` that writes `static/css/app.css`

## Run it locally

You need Python 3.12, PostgreSQL 16, Redis 7 and Node 22.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set DJANGO_DEBUG=true, DATABASE_URL, REDIS_URL, and generate the two keys it describes
createdb rasiko
python manage.py migrate
python manage.py bootstrap      # creates the Owner from OWNER_EMAIL / OWNER_PASSWORD, plus default settings
python manage.py seed_demo      # optional: demo categories, brands and drinks
(cd frontend && npm ci && npm run build)
python manage.py runserver
```

In other terminals, start the worker and the scheduler:

```bash
celery -A config worker -l info
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

The shop is at http://localhost:8000. The dashboard is at `http://localhost:8000/<ADMIN_URL>` (default `manage/`). Owners and managers must set up two-factor sign-in the first time they open it.

### Tests and checks

```bash
pytest                                  # uses config.settings.test
ruff check . && ruff format --check .
bandit -c pyproject.toml -r apps config
pip-audit -r requirements.txt
pre-commit install                      # runs ruff and bandit on each commit
```

GitHub Actions runs all of these, plus `check --deploy` and a Docker build, on every pull request.

## Deploy on a VPS (Docker)

This setup targets one Ubuntu server with 2 GB of RAM or more, with Docker and the Compose plugin installed and the domain's A records pointing at it.

1. **Get the code and settings.**
   ```bash
   git clone https://github.com/Satyajeetsinh-jadeja111/rasiko.git && cd rasiko
   cp .env.example .env && nano .env
   ```
   Fill in `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DOMAIN`, `OWNER_EMAIL` and `OWNER_PASSWORD`. Change `ADMIN_URL` and `DJANGO_ADMIN_URL` to paths only you know.
   Keep a copy of `FIELD_ENCRYPTION_KEY` somewhere safe. If it is lost, every key saved in the dashboard has to be entered again.

2. **Get the first TLS certificate** (port 80 must be free):
   ```bash
   source .env
   docker compose run --rm -p 80:80 --entrypoint certbot certbot certonly --standalone \
     -d "$DOMAIN" -d "www.$DOMAIN" --email you@example.com --agree-tos --no-eff-email
   ```

3. **Start everything.**
   ```bash
   docker compose --profile tls up -d --build
   ```
   On each start, `web` runs migrations and `bootstrap`, then serves the app. Nginx terminates TLS and the `certbot` service renews the certificate every 12 hours. After the first start, remove `OWNER_PASSWORD` from `.env`.

4. **Sign in** at `https://<DOMAIN>/<ADMIN_URL>`, set up two-factor sign-in, then go through **Settings**:
   - **Store settings**: name, address, phone, GSTIN, FSSAI number, invoice details.
   - **Delivery settings**: drop the store pin on the map, set the radius or draw the delivery area, set opening hours, fee slabs, the minimum order and the free-delivery thresholds.
   - **Integrations**: turn on only what you need (see below).

**Updates:** `git pull && docker compose --profile tls up -d --build`.

**Logs:** `docker compose logs -f web worker`.

### Adding keys in the dashboard

Open **Dashboard → Settings → Integrations** (Owner only). Each card has a switch, write-only key fields and a **Test connection** button. A service cannot be switched on while a required field is empty. Saved keys are encrypted and shown only as `•••• last4`. Every change is written to the audit log and emailed to the Owner.

- **Razorpay:** in the Razorpay dashboard, go to Settings → API Keys and copy the Key ID and Key secret. Under Webhooks, add `https://<DOMAIN>/payments/webhooks/razorpay/` with the events `payment.captured`, `payment.failed` and `refund.processed`. Set a webhook secret there and paste the same secret into Rasiko.
- **Stripe:** go to Developers → API keys and copy the publishable and secret keys. Under Webhooks, add `https://<DOMAIN>/payments/webhooks/stripe/` with `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`, `refund.created` and `refund.updated`, then paste its signing secret (`whsec_…`).
- **Email (Gmail):** turn on 2-Step Verification for the Google account, create an **App password** at myaccount.google.com/apppasswords, and paste it with host `smtp.gmail.com`, port 587 and TLS set to yes. Use **Send test email** in Settings → Email to confirm it works.
- **WhatsApp Business:** in Meta for Developers, create a WhatsApp app, then copy the phone number ID and a permanent system-user access token. Get an order-update template approved and enter its name.
- **Claude AI:** paste an API key from console.anthropic.com. The default model is a small, low-cost one.
- **SMS:** MSG91 (needs an approved DLT template ID) or Twilio.
- **S3 storage:** any S3-compatible bucket (AWS, Cloudflare R2, DigitalOcean Spaces). Restart `web` and `worker` after changing it.

### Backups and restore

The `backup` service writes a compressed database dump to `./backups` every day and keeps `BACKUP_KEEP_DAYS` days. Copy that folder, together with the `media` volume, to another machine or to cloud storage regularly.

To restore a dump:

```bash
docker compose stop web worker beat
gunzip -c backups/rasiko-YYYYmmdd-HHMM.sql.gz | docker compose exec -T db psql -U rasiko -d rasiko
docker compose start web worker beat
```

To test a restore, load the dump into an empty database first.

## Google Business Profile

A Google Business Profile helps "cold drinks near me" searches in Rajkot find the shop.

1. Go to business.google.com and add the business as **Rasiko**, category **Beverage distributor** or **Convenience store**.
2. Choose "I deliver goods to my customers", enter the service area (Rajkot and the pincodes you serve), and hide the street address if customers don't visit.
3. Use the same name, phone and address as in **Store settings**. The site publishes this data as structured data on every page, and Google compares the two.
4. Set the website to `https://<DOMAIN>` and the hours to match **Delivery settings**.
5. Verify the listing with the postcard, phone or video option Google offers, then add photos of the store and products.
6. Ask happy customers for Google reviews and reply to each one.

In Google Search Console, add the domain and submit `https://<DOMAIN>/sitemap.xml`.

## Languages

Customer pages are available in English, Gujarati (`gu`) and Hindi (`hi`); the dashboard is English. About half of the strings, including all navigation, cart, checkout and product-page text, have translations. The rest fall back to English. A native speaker should review `locale/gu` and `locale/hi` before launch.

After changing text in templates or code, run:

```bash
python manage.py makemessages -l gu -l hi --ignore=frontend/node_modules --ignore=static/vendor --ignore=staticfiles
# edit locale/*/LC_MESSAGES/django.po, then:
python manage.py compilemessages
```

## Project layout

```
apps/
  accounts      customers, addresses, OTP, 2FA
  catalog       categories, brands, products, variants, search, SEO
  inventory     stock, reservations, movements
  delivery      area checks, fees, ETA, store hours
  orders        cart, checkout, orders, invoices, subscriptions, party quotes
  payments      Razorpay, Stripe, COD, refunds, webhooks
  promotions    coupons, campaigns, combos, Rasiko Coins, referrals
  reviews       verified-buyer reviews with photos
  support       help center, chat, tickets, optional Claude AI
  notifications email, WhatsApp, SMS, admin alerts
  analytics     reports, funnel, insights
  dashboard     the staff dashboard
  core          settings, integrations switchboard, audit log, storage
config/         settings (base, dev, test, prod), URLs, ASGI, Celery
docker/         entrypoint, Nginx, backup script
docs/           PLAN.md, SPEC.md, projects_secret.md (where each key goes; holds no keys)
```
