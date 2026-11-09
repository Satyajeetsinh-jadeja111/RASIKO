# Rasiko

Rasiko is an online cold-drinks and beverages shop for Rajkot, built with Django. Customers get a storefront in English, Gujarati and Hindi with checkout, delivery-area checks, live order tracking, reviews and 24×7 help chat. Staff get a dashboard for orders, stock, products, offers, delivery rules, analytics and settings.

Every paid or keyed service starts **off**. The Owner switches it on and pastes its keys in **Dashboard → Settings → Integrations**. Keys never go in source code. Razorpay also supports private server environment keys as described below.

| Service | While off, the shop uses |
|---|---|
| Razorpay (UPI, cards) | Cash on Delivery |
| Stripe (cards) | Cash on Delivery |
| WhatsApp Business | "Order on WhatsApp" link (free `wa.me`) |
| Claude AI help chat | FAQ search, then hand-off to a person |
| Google Gemini AI help chat | FAQ search, then hand-off to a person |
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
   docker compose run --rm -p 80:80 --entrypoint certbot certbot certonly --standalone \
     -d your-domain.example -d www.your-domain.example --email you@example.com --agree-tos --no-eff-email
   ```

3. **Start everything.**
   ```bash
   docker compose build
   docker compose up -d db redis redis-cache
   docker compose run --rm release
   docker compose --profile tls up -d web worker beat nginx certbot backup
   ```
   The one-time `release` service runs migrations, bootstrap and static-file publication. Web restarts never run migrations. Run `release` for each new image before starting the application. Nginx terminates TLS and the `certbot` service renews the certificate every 12 hours. After the first start, remove `OWNER_PASSWORD` from `.env`.

4. **Sign in** at `https://<DOMAIN>/<ADMIN_URL>`, set up two-factor sign-in, then go through **Settings**:
   - **Store settings**: name, address, phone, GSTIN, FSSAI number, invoice details.
   - **Delivery settings**: drop the store pin on the map, set the radius or draw the delivery area, set opening hours, fee slabs, the minimum order and the free-delivery thresholds.
   - **Integrations**: turn on only what you need (see below).

**Updates:** back up and retain the previous image tag, pull the reviewed code, build or pull the new immutable `RASIKO_IMAGE`, then run `docker compose run --rm release` and `docker compose --profile tls up -d web worker beat nginx certbot backup`. Keep transactional traffic paused during schema/release changes. The release must succeed before serving the new code.

**Logs:** `docker compose logs -f web worker`.

### Adding keys in the dashboard

Open **Dashboard → Settings → Integrations** (Owner only). Each card has a switch, write-only key fields and a **Test connection** button. A service cannot be switched on while a required field is empty. Saved keys are encrypted and shown only as `•••• last4`. Every change is written to the audit log and emailed to the Owner.

- **Razorpay:** in the Razorpay dashboard, go to Settings → API Keys and copy the Key ID and Key secret. Under Webhooks, add `https://<DOMAIN>/payments/webhooks/razorpay/` with the events `payment.captured`, `payment.failed`, `refund.processed` and `refund.failed`. Set a webhook secret there and paste the same secret into Rasiko. Enable automatic capture in Razorpay and confirm the setting in Rasiko. Authorization alone never fulfills an order.
- **Stripe:** go to Developers → API keys and copy the publishable and secret keys. Under Webhooks, add `https://<DOMAIN>/payments/webhooks/stripe/` with `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`, `refund.created` and `refund.updated`, then paste its signing secret (`whsec_…`).
- **Email (Gmail):** turn on 2-Step Verification for the Google account, create an **App password** at myaccount.google.com/apppasswords, and paste it with host `smtp.gmail.com`, port 587 and TLS set to yes. Use **Send test email** in Settings → Email to confirm it works.
- **WhatsApp Business:** in Meta for Developers, create a WhatsApp app, then copy the phone number ID and a permanent system-user access token. Get an order-update template approved and enter its name.
- **Claude AI:** paste an API key from console.anthropic.com. The default model is a small, low-cost one.
- **Google Gemini:** paste an API key from aistudio.google.com (Get API key). The default model is `gemini-flash-latest`; when Google is busy the chat retries and falls back to other Flash models. If both Claude and Gemini are on, Claude is used.
- **SMS:** MSG91 (needs an approved DLT template ID) or Twilio.
- **S3 storage:** any S3-compatible bucket (AWS, Cloudflare R2, DigitalOcean Spaces). Restart `web` and `worker` after changing it.

### Backups and restore

The `backup` service writes a verified compressed SQL dump and a media archive to `./backups` daily and keeps `BACKUP_KEEP_DAYS` days. It detects dump/compression/archive failures and updates `last-success` only after successful completion. Container health becomes unhealthy if no successful backup is recorded within 25 hours. Monitor unhealthy status externally.

Local backups do not survive VM/disk loss. Configure an administrator-provided upload executable using `BACKUP_UPLOAD_COMMAND` and mount it, its runtime and restricted credentials into the backup container with a private Compose override. The executable receives the SQL and media archive paths and must exit nonzero on upload failure. No destination is configured by default. Keep `FIELD_ENCRYPTION_KEY` in a separate secure recovery store; never include it in project docs or logs. Archives may contain customer data: restrict access and encrypt off-server storage.

To restore a dump:

```bash
set -o pipefail
docker compose stop web worker beat
gzip -t backups/rasiko-YYYYmmdd-HHMMSS.sql.gz
gunzip -c backups/rasiko-YYYYmmdd-HHMMSS.sql.gz | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U rasiko -d rasiko
docker compose start web worker beat
```

Restore into an empty database first, never over a running shop. Extract the matching `.media.tar.gz` into an empty media volume, restore the encryption key from your secure recovery store, and verify accounts, images, orders and gateway configuration before switching traffic. SQL restore should use `psql -v ON_ERROR_STOP=1`. See the Oracle runbook below for release/rollback checks.

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


## Payment behavior and readiness

Choose the active provider in **Store settings**. By default only that enabled provider is offered, plus COD if enabled. Automatic fallback to the other configured provider is a separate, off-by-default setting. Existing orders keep their original gateway.

Razorpay Standard Checkout and Stripe Payment Element show eligible provider-enabled methods. Adding credentials cannot activate an unapproved account, unsupported currency/method, or restricted wallet. Follow the Integrations checklist: matching test/live keys, connection test, public HTTPS, signed webhook delivery, Razorpay automatic capture, then a complete sandbox payment/refund. Stripe India account availability is controlled by Stripe.

- Browser callbacks confirm provider status, amount, currency and identity. Razorpay must report `captured`.
- Individual failed payment attempts remain retryable until reservation expiry or explicit cancellation. Successful payments cannot be downgraded by delayed failures.
- Refreshes reuse the provider operation. Ambiguous Razorpay creates are looked up by their unique receipt instead of being submitted again. Ambiguous Stripe creation stops after 23 hours to avoid expired idempotency keys.
- Webhooks persist normalized identifiers/status data before processing; unfinished events retry. `unknown` returns HTTP 202 and remains pending until the local operation matches.
- Celery beat runs reconciliation every five minutes in bounded batches. Payment recovery covers the previous seven days; older unresolved payments require manual provider review. Refunds remain pending until confirmed. Never manually resubmit an uncertain refund without checking the provider.
- Refund amounts remain reserved during ambiguous outcomes. Restocking happens on successful refund confirmation and actual stock returns are tracked separately from financial refunded quantities.
- Payments arriving after timeout/cancellation are flagged as **refund required; do not fulfill**, because stock/discounts/coins may already have been released.
- Switching checkout off retains historical webhook/refund processing. Removing or replacing credentials can prevent recovery of old payments; finish unresolved operations before rotating account/mode keys.
- Integrations shows pending webhook and uncertain operation counts. Read provider dashboards alongside these counts; connection success is not a complete readiness check.

## Oracle Always Free runbook

Default sizing is one Ubuntu LTS Ampere A1 ARM64 VM, **2 OCPUs / 12 GB RAM**, only when the OCI console confirms this is within your tenancy's Always Free allowance and capacity exists. Use your eligible home region, preferably close to Rajkot. Check current Oracle limits before provisioning; do not assume trial credits or older 4-core allocations remain free.

1. Attach only eligible boot/block storage. Set budget alerts and confirm every resource is free before creating it.
2. Install Docker Engine and Compose from the official repository. Build the image in CI/on another machine and transfer or pull the immutable ARM64 image to keep compilation off the shop VM. CI builds AMD64 and ARM64 using QEMU; local ARM64 builds need native ARM hardware or configured emulation.
3. Restrict SSH to your administration IP. Open inbound TCP 80/443 in both OCI network security rules and the OS firewall. Do not expose database or Redis ports. Point the domain's A records at the VM; configure AAAA only if IPv6 actually works.
4. Fill `.env.example`, set immutable `RASIKO_IMAGE`, obtain the first certificate, and follow the release commands above. Percent-encode special characters in database/Redis URLs.
5. Set `WEB_WORKERS=2`, `WORKER_CONCURRENCY=1`, `DB_CONN_MAX_AGE=0`, `EMAIL_SEND_INLINE=false`. The cache uses `redis-cache` with eviction; Celery and Channels use the persistent, non-evicting `redis` service. After upgrading an existing deployment, update all three Redis URLs to match `.env.example`.
6. Nginx serves collected static files from the release-populated shared volume. Hashed files are immutable; original filenames use short caching. The Nginx wrapper renders only DOMAIN and reloads changed certificates. Certbot renews through the shared webroot.
7. Monitor `docker compose ps`, container health, disk space, restart counts, Celery backlog, payment recovery counts and off-server backups. `/healthz` is liveness; `/readyz` checks database, cache and broker and is restricted at Nginx. Web health checks use the configured domain Host header.
8. Perform an isolated restore and a release rollback drill before launch. Retain previous image tags and backup pairs. Revert code only if its schema compatibility is known; do not reverse financial data migrations or restore an old database without reconciling provider transactions received since the backup.

The Compose memory limits leave room for the OS and filesystem cache. Tune workers, connection counts and limits from measured p95 latency, CPU, memory and queue lag. Always Free is a single-server deployment; independent backups are required for recovery from reclaim or disk loss.

## Performance and mobile verification

Public homepage/catalog fragments cache for 30 seconds with invalidation on catalog changes; customer/cart data is rendered separately. Checkout always revalidates authoritative stock and totals. New product uploads generate WebP derivatives; backfill existing images with:

```bash
python manage.py build_responsive_images
```

Use the mobile-first route/state checklist and evidence in `docs/audit/`. Check 320, 375, 390, 768, 1024 and 1440 px, keyboard navigation, 200% zoom, reduced motion and all three languages. A visual screenshot alone does not establish accessibility compliance. Development service workers unregister to avoid hiding CSS updates; production caches only versioned static assets.

Before launch, measure a representative catalog with 20 concurrent browsing users and five checkout users. Targets are warm browsing p95 server response below 300 ms, mobile Lighthouse performance at least 90, no application errors and no overselling. Local debug/demo measurements are not Oracle production benchmarks.

## Living documentation and AI handoff

Start with `project.md` and `AGENTS.md`. Every meaningful batch updates the handoff with actual changes, decisions, migrations/configuration, checks, blockers and next steps. Update this README whenever guidance changes. These files are maintained with code, rather than automatically inventing release notes.

```bash
python3 scripts/docs_guard.py --base <base-commit-sha>
# Without Git, pass the actual changed paths, including documentation:
python3 scripts/docs_guard.py --files apps/payments/services.py project.md README.md
```

CI requires `project.md` changes for implementation changes and README review for operational changes. The PR checklist requires content review; filename checks cannot prove accuracy. Never record credentials or customer data in either file.

### Verified implementation and release gates

Read [project.md](project.md) first for the current implementation, checks and resume instructions. [The audit report](docs/audit/REPORT.md) links actual browser evidence and distinguishes local verification from release prerequisites. Local DEBUG load measurements do not satisfy the Oracle latency target; do not treat query-count reductions as a production benchmark.

Use Python 3.12 for installs and CI. The old local Python 3.10 virtualenv is not a supported production runtime. Autobahn is explicitly pinned to 26.7.1 to address the dependency audit finding; validate the complete Python 3.12 environment before release. After migrations, old pending financial operations are treated as uncertain and reconciled rather than blindly resubmitted. Review the integrations recovery counts after upgrading.

Refunds require a collected payment, including collected COD. Customer cancellation reserves only the remaining balance after existing pending/successful refunds, in the same transaction as cancellation. Uncertain or failed provider refunds need reconciliation/staff review; cancellation alone is not proof that the customer has received a refund.

Production settings always queue email through Celery, including when a legacy environment sets `EMAIL_SEND_INLINE`. Keep the worker and scheduler running and monitor delivery failures/backlog.

### Real-brand photo starter catalog

For a local demo with actual branded drink photos, first create categories (on a fresh demo database, `seed_demo`), then run:

```sh
python manage.py seed_branded_catalog --acknowledge-demo-prices --replace-fictional-demo
```

This installs 32 photographed product records, with 28 active. Bailley water is limited to the owner’s available purple 250 ml/500 ml/1 L and pink Bailley One 1 L; 2 L/5 L/10 L/20 L records remain hidden. Three Bailley Soda sizes remain available. Cards explicitly show “Demo price.” Prices, taxes (zero placeholders), stock (60 bottles), provisional box sizes and jar deposit/return rules require owner review before launch. Ordinary repeated runs preserve edited prices, stock and existing photos. The owner-approved demo configuration is 24 units up to 600 ml, 12 units from 750 ml through 1 L, and 6 units above 1 L; prices are per whole box (demo bottle reference price × box count). To explicitly convert an existing starter demo, add `--configure-demo-boxes`; this resets starter box prices/counts/availability while preserving bottle stock and historical orders. Do not use that flag after entering real business prices. The optional replacement flag deactivates original fictional demo products/variants and affected combos while retaining history. This is an explicit demo command, never part of release/bootstrap.

`assets/starter-catalog/catalog.json` records photo provenance; see its README for source and packaging limitations. Supplier-approved photos are required for the live shop. Upload replacements through the product editor; normal uploads generate responsive derivatives. Preserve the media volume across restarts and include it in backups. The isolated preview now uses filesystem media storage; tests use isolated/in-memory storage.


### Whole-box product entry

Customers purchase whole boxes; quantity 1 means one box. Variants configured with fewer than two bottles per box are unavailable to buy. In Dashboard → Products, admins must provide the bottle size label, volume of one bottle in ml, and bottles per box (at least 2). Enter selling price, MRP and cost per box; stock and adjustments remain counts of individual bottles. CSV import also requires `units_per_box` and `volume_ml` values on every row. Review demo prices and actual supplier case counts before launch.

### Docker translation-build troubleshooting

If an older image build fails at `django-admin compilemessages` with `No module named config`, pull the Dockerfile fix and run `docker compose build web` again. Both asset commands now run through `python manage.py` with temporary build-only settings credentials in the same build step. Keep production secrets in `.env`; do not copy them into the image or regenerate existing keys to resolve a build failure.


## Razorpay Standard Checkout: server-managed keys

The existing Razorpay Python SDK is already included in `requirements.txt`. Keep the private `.env` out of Git and Docker build contexts. Configure these server variables without copying real secrets into documentation:

```dotenv
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
RAZORPAY_WEBHOOK_SECRET=your_separate_webhook_secret
RAZORPAY_ENABLED=false
```

Both environment API keys must be supplied to override dashboard API keys. A saved disabled Razorpay dashboard integration remains disabled; enable it deliberately in Dashboard → Settings → Integrations. When no dashboard integration exists, `RAZORPAY_ENABLED=true` explicitly enables environment configuration. A saved enabled integration remains enabled independently of this fallback flag. Historical verification/webhooks can still use available credentials after checkout is disabled. Select Razorpay as the shop's online gateway and configure capture and webhooks before live use.

The authenticated payment page opens Standard Checkout only when the customer presses its payment button. It posts to `/payments/pay/<order-public-uuid>/create-order/`, which uses the owned shop order's total in paise, INR and existing receipt; browser-supplied totals are ignored. Amounts below 100 paise are rejected. Existing provider orders are reused. The response includes `order_id`, `amount`, `currency` and public Checkout fields, never the API secret.

Checkout sends `razorpay_payment_id`, `razorpay_order_id` and `razorpay_signature` to `/payments/pay/<order-public-uuid>/verify-payment/`. Both endpoints require POST, an authenticated order owner and Django CSRF protection. Verification checks the callback order against the stored provider order, HMAC-SHA256 signature and provider capture status, amount and currency before fulfillment. Signature failures or missing fields return 400; unauthenticated requests return 401. Creation authentication failures return 401 and other provider failures return 500. Interrupted verification returns 503 with instructions to avoid paying twice; existing webhook/reconciliation processing handles eventual confirmation.

To test: start the usual local stack, enable Razorpay using test keys, sign in, place a box order with Razorpay and press the payment button. Confirm success, dismissal and failure messaging; confirm the order becomes paid only after capture. Configure the existing `/payments/webhooks/razorpay/` endpoint with its separate webhook secret, then verify signed webhook delivery and reconciliation. Use provider test-mode payment details from [Razorpay's test integration guide](https://razorpay.com/docs/server-integration/python/test-app/). Provider account activation and payment-method eligibility are separate from installing keys.

Automated regression checks (use an isolated PostgreSQL database with permission to create a test database):

```bash
pytest apps/payments/tests
node scripts/test_payment_checkout.cjs
```

After deploying this code to Oracle, add the private keys to the server's existing `.env`, preserving its database and encryption secrets. Rebuild the release and recreate web/worker/beat containers so they read the new environment. No schema migration is introduced by this change. Do not assume a local environment file updates the Oracle server. Verify a sandbox purchase and webhook delivery there before switching to live keys.


## Login and box-stock troubleshooting

Login failure lockouts apply to the combination of normalized email and client IP (five failures, one-hour cooldown); a different customer sharing that IP can still log in. A broader 60-POST-per-minute IP throttle protects the login endpoint. Keep trusted proxy/IP handling configured correctly in production. Email login is case-insensitive, including older mixed-case stored addresses. Account creation and password changes on Oracle do not automatically update your local database, or vice versa.

A bootstrap `.env` password is only for initial owner creation: changing it does not reset an existing account. To reset a forgotten local owner password, run the following from the project directory and enter your new password privately when prompted (no password is placed in shell history):

```bash
DJANGO_SETTINGS_MODULE=config.settings.dev ../.venv/bin/python manage.py shell -c 'from apps.accounts.models import User; from django.core.management import call_command; owner = User.objects.get(role=User.Role.OWNER); call_command("changepassword", owner.email)'
```

This assumes the local virtual environment is one directory above the project and exactly one owner exists. The normal email password-reset flow requires working SMTP. Do not reset all user passwords or disable login protection to fix a single account.

An old single-bottle demo database will show products unavailable under box-only rules. A sellable variant needs an active product/variant, at least two bottles per box, valid bottle volume, no manual out-of-stock flag, and enough unreserved bottles for a complete box. Configure real stock, box size and box price through the dashboard; do not invent stock to enable a real sale. For a local demo only, the approved bundled branded catalog can be restored with:

```bash
python manage.py seed_branded_catalog --acknowledge-demo-prices --replace-fictional-demo --configure-demo-boxes
```

This requires starter categories, installs demo stock for newly created starter products and resets starter box sizes/prices/availability explicitly. It preserves existing starter bottle stock, photos and historical orders. Never run this command on a live catalog without reviewing its demo data and obtaining explicit authorization.


### Razorpay test bank popup stays blank

Checkout pages use `Cross-Origin-Opener-Policy: same-origin-allow-popups` so bank/payment windows can retain their opener reference; other pages retain `same-origin`. Keep this exception scoped to checkout. Failure messages display only sanitized Razorpay error code/reason labels, not provider metadata or account identifiers.

Use current [official Indian test card details](https://razorpay.com/docs/payments/payments/test-card-details/): Visa `4100 2800 0000 1007`, any random CVV and a future expiry date. Follow the simulated bank screen: choose Success if offered, or submit a 4–10 digit test OTP if prompted. A test key is not a card number. If the popup remains blank after a hard refresh, record the browser console/network error and check popup permissions and browser extensions for this site before attributing it to a gateway decline. Do not scan a test QR with a real banking app to validate card authentication. A provider payment in `created` is not a successful capture and must not fulfill an order.


### Oracle SSH access guide

Step-by-step instructions for this owner’s laptop, the SSH command, connection checks and safe log inspection are in [the SSH section of the secrets guide](docs/projects_secret.md#e-access-the-oracle-server-through-ssh). The guide contains key-file references only; private keys and environment credentials must stay outside documentation. Verify the instance public IP and host fingerprint before connecting.

## Marketplace, brand Heads and Rasiko Rider

New partner workspace: `/partners/`, also linked from the Owner dashboard. Owner, brand Head and seller accounts use two-factor authentication. Head/seller/rider roles do not inherit the global staff dashboard. Marketplace switches default **off**; apply and test migrations before opening the workspace.

The backend supports brand-scoped Heads across states/regions/areas, seller teams, exclusive brand/pincode assignments, territory requests, seller-funded coupons, separate seller/brand fulfillment orders, COD policy defaults/global overrides, rider invitations and dispatch APIs, stock/product editing and add-only CSV imports, fee notices, seller financial entries and translation review. The detailed setup, seller-money examples, release gates and remaining work are in [the marketplace operating guide](docs/MARKETPLACE_GUIDE.md).

New migrations: `accounts.0003`, `catalog.0005`–`0006`, `marketplace.0001`–`0004`. Existing shop ownership is backfilled using the preview-first `backfill_marketplace --owner-email ...` command; add `--apply` only after reviewing a backup/restored database. It does not invent historic payouts. No migration or ownership backfill is automatically run against the live shop.

Optional integrations in Owner Settings → Integrations:

- **Google Cloud Translation**: restricted Google Cloud Translation API key. Translation failure leaves source content visible; ingredients/allergens require review before translated publication.
- **Rasiko Rider push (FCM)**: encrypted Firebase service-account JSON. Configure Android Firebase and iOS APNs separately. Phone permissions/settings govern sound.
- **Razorpay Route**: existing Razorpay credentials plus separately approved linked seller accounts. Keep `MARKETPLACE_ROUTE_APPROVED=false` and Payouts off until provider sandbox, refund/reversal and bank-settlement acceptance checks are complete. Standard Checkout configuration alone does not approve Route.

Celery beat adds a gated 15-second dispatch scan and five-minute transfer recovery scan. Dispatch uses 45-second offers, two retries, 30-second rider heartbeats and 90-second stale detection. New mobile APIs are under `/api/v1/rider/` with short-lived opaque bearer tokens stored hashed on the server. Browser mutations retain Django CSRF protection.

Flutter Android/iPhone source is in [mobile/rasiko_rider](mobile/rasiko_rider/README.md). Static analysis and two multilingual Flutter widget tests passed; generated Android/iOS projects include location-stream configuration and sound resources. The Android debug APK now builds with the project-local two-worker/1536 MB profile. Release signing, IPA builds and physical-device notification/background validation remain unverified; iOS needs macOS/Xcode. Transfer reversal recovery and final bank-settlement polling are now implemented with mocked-provider tests; real provider transactions, signing and phone acceptance still gate production payouts and app-store release. The guide separates these prerequisites from locally verified backend behavior.

Regression tests should use an isolated PostgreSQL database and `ADMIN_URL=manage` because existing dashboard tests assume that test URL. Never point tests at production.


## Marketplace and seller teams

See [the owner/seller operating guide](docs/MARKETPLACE_GUIDE.md) and [Rider app setup](mobile/rasiko_rider/README.md). `/partners/` requires an authorized seller/Head/admin with two-factor authentication; invitation-based rider APIs are under `/api/v1/rider/`. Marketplace, dispatch, translation and payout switches start off. Admin global overrides take priority while preserving historical order policies.

Apply catalog migration 0006 and marketplace migration 0004 on a restored database first. Preview `python manage.py backfill_marketplace --owner-email <owner-email>` before using `--apply`; reconcile historical totals, stock and payments. This session did not migrate the live shop or enable production features.

Keep Celery worker and beat running: dispatch checks every 15 seconds, settlements reconcile on their configured schedule, operational alerts/retention every five minutes. Approved Route access additionally requires `MARKETPLACE_ROUTE_APPROVED=true`; normal Razorpay Checkout credentials do not establish Route approval. Sellers submit encrypted legal/bank data in their partner onboarding form. Uncertain provider creations require reference verification; never retry by creating another linked account. Heads cannot change payout destinations.

`python manage.py marketplace_readiness [--strict]` reports redacted local prerequisites without provider calls or enabling features. Configure grievance contacts, privacy/terms, supplier invoice details and territory GST state codes before pilot orders. Seller invoice PDFs require the pinned HarfBuzz dependency and bundled OFL-licensed Noto fonts. Invoice generation does not implement statutory withholding, credit notes or e-invoice/IRN registration.

Recovery: disable the affected feature switch, preserve financial records, investigate uncertain operations by saved provider references, and reconcile refunds/transfers/bank settlement before resuming. Back up database and the encryption key together using existing private backup procedures. Do not roll financial migrations back or delete disputed ledger rows to clear alerts. Firebase/APNs credentials, platform signing and real phone acceptance remain separate release prerequisites; foreground rider polling works without Firebase while the app stays open.


For a reproducible Android development build, use `scripts/build_rider_android.sh` with the persistent workspace `.rasiko-tools/` SDKs described in the Rider README. Generated APKs stay under ignored `artifacts/`; source does not include private Firebase or signing files. The helper validates source/widgets and builds only; it does not deploy the server or switch on production dispatch/payouts.


On the 8 GB Ubuntu development laptop, Android builds use the project-local two-worker, nonparallel, 1536 MB heap profile in `mobile/rasiko_rider/android/gradle.properties`. The Ubuntu helper serializes mobile builds and lowers CPU/disk priority. Existing running builds retain their original settings; the new profile starts with the next invocation. See the Rider README for details; global Gradle settings are unchanged.

Android debug build verified on 2026-10-24 with the new resource profile (2m 20s). The generated `artifacts/rasiko-rider-debug.apk` is for development testing, targets `https://rasiko.in` and has Firebase push off. Device acceptance, backend deployment/configuration, real Route sandbox operations and iOS signing/testing remain separate release gates.


Head setup: create service territories through **Partner workspace → Add area** before **Add brand Head**. Register a separate Head account first. Brands and territories use checkboxes; multiple selections need no Ctrl/Command key. An empty territory list means no areas have been created.

Independent sellers may sell multiple brands. Sellers with an active Head-managed team need admin permission for additional active brands, under **Seller verification and linked account → Allow multiple brands for this Head-managed seller**. Multiple Heads can share a brand while retaining separate jurisdiction grants. Apply `marketplace.0005` before using this control. See the marketplace guide for area setup and reassignment rules.

For USB-connected Android Rider tests against this laptop, see the Rider README's USB-local instructions. The separate debug artifact uses an explicit loopback-only opt-in plus adb reverse; ordinary/release builds still require HTTPS. No Wi-Fi/public server exposure is needed.

## Seller shop workspace

Seller applications now accept multiple brands and service areas and immediately create a private shop workspace. Sellers use **Manage my shop** in `/partners/` to edit their shop, review setup/approval, manage approved catalog and stock, request extra brands/areas, invite riders and access scoped orders/income/payout tools. Head-managed sellers still require admin permission for extra active brands. Heads can hold multiple brands and areas across states.

Migration `marketplace.0006` adds shop description and publication preference; apply it on restored staging first. Existing sellers keep their accounts/history and begin unpublished. Buyer shop pages `/shops/<id>/` require verification, active seller/brand/territory and publication. The Rider app continues using the same seller affiliation and versioned APIs. See the operating guide for review/staging steps; production deployment is intentionally separate from pushing a review branch.

The November 9 review also updates audited dependency pins (REST framework, Autobahn, Twisted, Pillow and Black) and pins requests. The development environment was audited again after installation; use Python 3.12 and rerun the full checks in staging. Existing broad storefront translations and native/platform/provider acceptance still need their documented release checks.
