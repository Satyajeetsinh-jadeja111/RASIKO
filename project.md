# Rasiko — project handoff

Last updated: 2026-10-22. Read this file first, then README.md, AGENTS.md and docs/audit/REPORT.md.

## 2026-10-22 — marketplace and brand-team implementation

Intent: add brand Heads managing multi-state seller teams and territories, seller-owned riders, scoped marketplace fulfillment, multilingual partner operations and transparent seller accounting.

Implemented locally:
- Added `apps.marketplace`: canonical pincode territories, exclusive brand assignments, Head/brand/area grants, seller applications/invites/verification, team activation/suspension, reasoned territory requests, nullable global COD/online overrides, seller-funded scoped coupons, persistent/email notices and seven-day platform fee policies.
- Added `/partners/` with mandatory 2FA, role/brand/territory-scoped dashboards and CSV exports, daily delivered-revenue summaries, COD/online balances, fulfillment queue, rider availability, product/box editing, stock adjustments, add-only transactional CSV import and translation review. Heads/sellers/riders do not acquire global staff dashboard/WebSocket access.
- Integrated marketplace preview/checkout/payment creation: seller-brand child fulfillment orders, service-pincode validation, standard estimates, COD-only mixed-cart rules, exact paise allocation, immutable fee/policy snapshots, scoped coupons and payment-policy revalidation. Existing shop behavior remains behind the default-off feature switch.
- Added invitation-only rider registration, hashed bearer tokens, consented heartbeat/location APIs, 45-second offers with two retries, atomic first acceptance and one active assignment per rider, pickup/delivery OTP and idempotent COD custody/remittance. Buyer OTPs are encrypted at rest and visible only on owned order pages; wrong attempts are limited.
- Added source-hashed Google Translation caching with protected brands/numbers, review gates for ingredients/allergens, source fallback and manual correction. Hindi/Gujarati partner navigation catalogs compiled; native/complete form-error review still required.
- Added financial ledger/refund allocation and conservative Route transfer claim/recovery. Uncertain creates use source-payment lookup and never blindly resubmit. Pending refunds/disputes hold payout; post-transfer refunds are flagged for recovery. Payouts remain default off with an additional `MARKETPLACE_ROUTE_APPROVED=false` gate.
- Added Flutter Rider Android/iOS projects, existing-brand icons, custom sound resources, consented platform location streams, secure storage and a resolved dependency lockfile. This is not an app-store release.

Configuration/migrations: `accounts.0003`, `catalog.0005`, `marketplace.0001`–`0003`; optional encrypted Owner integrations `google_translate` and `rider_push`; gated Celery beat dispatch (15 seconds) and transfer recovery (five minutes). `backfill_marketplace --owner-email ...` previews by default; `--apply` explicitly attaches legacy ownership/fulfillment snapshots without changing historic totals or creating old payouts. All new operational switches remain off.

Verified:
- Django system check: no issues. Migration generation check: no changes detected. New migrations applied successfully only to an isolated synthetic preview database.
- Affected backend suites: **189 passed** against an isolated PostgreSQL 14 test cluster on port 55439, with `ADMIN_URL=manage` matching existing dashboard tests. Earlier run with the private local staff URL stopped on three hard-coded-route tests; corrected environment rerun passed.
- Final focused marketplace suite: **32 passed**, including real concurrent acceptance through separate DB connections, cross-brand/territory isolation, mixed-brand checkout, invitation registration, stale/expired offers, OTP visibility, fee notice period, refunds, payout uncertainty, CSV rollback, translation safeguards, seller application and preview-first backfill.
- Ruff check and formatting passed for changed Python modules; Bandit passed for the marketplace app; documentation guard passed. Translation catalogs compiled. Tests warn that collected staticfiles are absent in the development tree; this was not a production static-assets build.
- Real in-app browser with synthetic Head/seller data: login and TOTP, desktop and 320px partner dashboard, Hindi and Gujarati language switching. At 320px viewport, document client/scroll widths were both 305px (scrollbar excluded), so no page overflow; tables scroll within containers. Screenshots: `docs/audit/marketplace-head-desktop.png` and `marketplace-head-gujarati-mobile.png`. These are new screens; no prior marketplace screen existed for a before capture.

Incomplete / release gates:
- Flutter static analysis passed and two multilingual widget tests passed with temporary Flutter 3.29.3 / Dart 3.7. Android/iOS projects were generated, sound resources and permissions configured. A debug Android build was attempted and stopped during Gradle setup: this host has only Java 11 and no Android SDK platforms/build tools. JDK 17+, complete Android SDK, macOS/Xcode signing and physical-device push/background validation remain required. Platform background-location source is implemented but not field-verified; no APK/IPA is verified.
- Provider account/KYC creation automation, actual Route sandbox capture/transfer/refund testing, automatic post-transfer reversal recovery and final bank-settlement confirmation. Do not enable payouts before these are accepted; loyalty subsidies exceeding the captured source payment are held for funding review.
- Seller-specific statutory invoices/business verification workflows, expiry/batch inventory, dedicated seller support inbox, full multilingual form/error/structured-data coverage, native translation review, operational telemetry/retention policies and country-specific legal/tax requirements.
- No Oracle/production deployment, live migration, live gateway configuration, real customer messaging or money movement was performed. Working folder has no Git metadata, so no commit/PR was created.

Owner/seller setup and money-flow guide: `docs/MARKETPLACE_GUIDE.md`. Native app source notes: `mobile/rasiko_rider/README.md`.

## Architecture and decisions

Django server-rendered storefront and staff dashboard; Tailwind/HTMX/Alpine; PostgreSQL business state; Redis cache and Channels; Celery background work; Nginx/TLS and Docker Compose. Production runtime is Python 3.12/PostgreSQL 16. Preserve the warm light brand, Vastu placement and English/Gujarati/Hindi support. Mobile first.

One owner-selected online gateway plus COD. Credentials enable integration; provider approval, eligible methods, correct capture settings, HTTPS and signed webhooks remain required. Cross-gateway fallback is an explicit owner opt-in and defaults off. Historical events/refunds can use disabled integrations if their saved credentials remain available.

## Current status

Core implementation is in place and locally tested. This is **not launch approval** or a claim that every acceptance item is complete. No live database, gateway configuration or Oracle host was modified. External provider sandbox, Oracle production measurements, ARM64 execution and full accessibility/state coverage remain release gates.

## 2026-10-09 — payment and stock reliability

Purpose: stop duplicate fulfillment, uncertain network retries and financial/stock races.

Implemented in `apps/payments`, `apps/orders`, `apps/inventory`, `apps/core` and dashboard integrations/order settings:

- Razorpay callback success requires valid signature plus provider-captured status, matching order, amount and currency. Stripe success requires a succeeded matching intent, amount and currency. Provider-managed eligible methods remain in Standard Checkout/Payment Element.
- Order-first row locks serialize payment/refund mutations. Payment initialization records a durable claim before network calls, reuses saved provider orders/intents and rejects concurrent initialization. Ambiguous creates use provider receipt/idempotency lookup; old Stripe uncertainty beyond its safe retry window requires manual review.
- Durable normalized webhook receipts track pending/processed/rejected, attempts, error class and processing time. Business mutations roll back on crashes while pending receipt survives for recovery. Duplicate/out-of-order failure cannot undo success. Unknown objects remain retryable; reconciliation prioritizes least-attempted receipts to avoid starving newer events.
- Refund reservation is persisted before provider calls, which occur outside DB locks and after surrounding transactions commit. Timeouts preserve pending amounts/line quantities; recovery looks up existing refunds rather than blindly submitting again. Stock is restored on confirmed success only. Uncollected COD/other unpaid orders cannot be refunded.
- Customer cancellation and remaining refund reservation are atomic, including existing pending/completed partial refunds. Failures in reservation roll back cancellation. Provider submission remains after commit.
- Late successful payments on cancelled/expired orders are recorded financially but never silently fulfilled; staff receives a refund-required note. Additional payments are flagged for review.
- Separate actual `OrderLine.restocked_qty` prevents pending financial refund quantities from suppressing cancellation restock or causing later double restock. Reservation changes invalidate shared catalog cache.
- Celery reconciliation runs every five minutes with bounded batches and per-operation due checks. Integrations screen exposes test/live, HTTPS, connection, signed delivery since change, owner capture confirmation and unresolved recovery counts. Provider errors shown to users are redacted; decrypted settings are not cached in Redis. External calls have explicit timeouts.

Migrations (all applied successfully to the isolated review DB):

- `core.0002_storesettings_gateway_fallback_enabled`
- `payments.0002_payment_creation_started_at_and_more`
- `payments.0003_preserve_historical_operations` (old receipts marked processed; old pending operations treated as uncertain; historical restock flags preserved)
- `orders.0004_orderline_restocked_qty`
- `orders.0005_backfill_actual_restock` (backfill from positive refund/cancellation stock movements)
- `catalog.0004_productimage_responsive_images`

These are additive migrations with conservative financial backfills. Back up before production migration; do not reverse financial data migrations casually. Audit ambiguous historic operations after upgrade.

## 2026-10-09 — mobile and professional presentation

Implemented shared bounded empty state (80 px mobile, 96 px larger screens), recovery copy/actions, cart reuse, collapsible mobile filters/open desktop filters, loading/busy indicators, touch/input/focus/reduced-motion rules, proportional header/chat branding and defensive wrapping. Added Gujarati/Hindi empty-search translations and compiled catalogs. Compiled Tailwind output is updated.

Browser evidence confirmed the original oversized graphic and verified the fix. Auditing all 29 dashboard navigation routes exposed shared navigation overflow (3,232 px), then slider and delivery-hours overflow. Fixed grid minimum widths, responsive slider editor rows and contained table scrolling. Public fragments stay cached server-side; HTML and transactional responses are private/no-store. Readiness bypasses coming-soon launch gating.

Evidence and coverage limitations are in `docs/audit/REPORT.md`. Screenshots/DOM metrics are real browser captures using synthetic fixtures. COD checkout and staff fulfillment through delivery were completed. The synthetic manual cash refund initially timed out in browser control, then was confirmed succeeded in the isolated database and the recovered staff page (`staff-refund.jpg`). No real money moved. Final Gujarati/Hindi empty-state screenshots and signed-in 320 px layout were also checked.

## 2026-10-09 — Oracle deployment, performance and recovery

Implemented two web workers/one Celery process defaults, ASGI persistent DB connections disabled, release-only migration/bootstrap/static copy, resource/log limits, independent evictable cache Redis and durable no-eviction broker Redis, queued production email/WhatsApp work, Nginx hashed-static caching/compression, explicit template substitution, certificate reload watcher, and DB/cache/broker readiness.

New product uploads produce responsive WebP derivatives with actual pixel-width srcsets; existing uploads require `build_responsive_images`. Shared public home/footer/campaign/catalog context caches invalidate on catalog changes. Warm demo queries: home 20 → 1, search 11 → 9, empty search 8 → 6, cart 3 → 1.

Backup writes/validates SQL and media before renaming, propagates dump/upload failures and updates success marker only after success. Optional off-server upload hook is documented but no remote destination is configured. Actual isolated database restore and synthetic media verification passed. README contains Oracle entitlement, firewall/DNS/TLS, release, restart, rollback, backup/key-recovery and restore guidance.

CI adds QEMU-backed AMD64/ARM64 builds and documentation checks. Autobahn pinned to 26.7.1 after audit detected PYSEC-2026-4027 in the old transitive 24.4.2. Patched runtime installation requires supported Python 3.12; the original local Python 3.10 virtualenv still has the old transitive dependency and must not be deployed.

## Verified locally

- Final clean full regression suite: **159 passed**, 66 warnings about absent development collectstatic output (Python 3.10, PostgreSQL 14 isolated DB).
- Earlier targeted stock/cache/image suite: **10 passed**, including concurrent last-stock competition. Image/cache/privacy suite: **3 passed**. Both are included in the final 159-test full run (180.18 seconds).
- Payment regressions cover captured/authorized distinction, mismatches, duplicate/out-of-order/crashed processing, historical disabled credentials, gateway selection, provider reuse/timeouts, recovery batching, concurrent initialization, late success, uncertain refunds, cancellation/partial refunds and actual restocking.
- Ruff checks/formatting, migration consistency, Django production `check --deploy`, Bandit, shell syntax, isolated Nginx `nginx -t` with throwaway TLS certificate and synthetic Compose validation passed. Production settings force email work through Celery even if an old environment requests inline sending.
- Backup failed dump/upload tests passed; successful dump restored with SQL stop-on-error to a separate empty DB; synthetic media content matched.
- Six-width representative route checks show no page overflow. All dashboard navigation destinations captured at mobile width; full state/editor/accessibility coverage remains incomplete.
- Local load: 300/300 HTTP 200, 20 browsing + 5 checkout-page users. Browsing p95 2,334.8 ms, checkout-page p95 1,914.8 ms under DEBUG/Django Client. **300 ms target not met.** This excludes provider calls and actual checkout submissions and is not an Oracle benchmark.
- Independent security reviewer required by original SPEC inspected the payment/stock changes, identified issues that were fixed, and found no further blocker in the final targeted static review. This is not a formal security certification.

## Blocked / remaining release acceptance

1. Real Razorpay/Stripe sandbox checkout, signed webhook delivery, capture readiness and uncertain refund recovery need test accounts and HTTPS endpoint. No credentials were requested or changed.
2. Oracle A1 availability/Always Free entitlement, domain/TLS, actual ARM64 release, real workload p95, mobile Lighthouse >=90, real off-server recovery and production rollback need the deployment environment. Local ARM64 build failed because this host lacks emulation. QEMU CI is configured but has not run here.
3. Native Python 3.12 production image build remains unverified. The first attempt failed on a transient package-index resolution error; retries resolved the dependency but were interrupted or stalled during downloads. The final retry was stopped after several minutes without visible progress on the Django wheel download. Apt dependencies and CSS stages completed, but Python installation/image assembly did not. No image has been deployed. Rebuild on a reliable network before release, rerun the suite under Python 3.12, and audit the installed dependency set.
4. Complete every route/state accessibility review: keyboard, focus/contrast, screen reader, 200% zoom, long translations, CRUD/detail/permission/error states, subscriptions, reviews, support/chat and online payment dialogs. Route screenshots alone do not certify these.
5. Resolve production latency using measurements; do not claim “super fast” from query reductions. Existing mixed English/Gujarati/Hindi copy needs a translation completeness pass.
6. Configure off-server backup upload and protect/rehearse encryption-key recovery. Empty placeholders for business phone/FSSAI/GST in demo data must be replaced with validated shop configuration before launch.

## Living documentation

AGENTS.md requires every meaningful change to update this handoff and operational changes to update README. `scripts/docs_guard.py`, CI and PR checklist enforce file-level updates; accuracy remains a human/agent review responsibility. No credentials/customer records belong in these files.

## Exact resume instructions

1. Work in `RASIKO-build-full-shop`. Original Markdown read: README.md, docs/PLAN.md, docs/SPEC.md, docs/projects_secret.md. Historical plans may be stale; current status is here.
2. Use Python 3.12 and an isolated PostgreSQL DB with CREATEDB permissions, then install requirements-dev.txt, run migrations and `pytest --create-db` serially. Never point tests at shop `.env`. See README for production commands.
3. Temporary local review DB is PostgreSQL 14 on loopback port 55432, DB `rasiko_review`, user `test`, cluster `/tmp/rasiko-review-pg`; review settings `/tmp/rasiko_review_settings.py`. Command used: `PYTHONPATH=/tmp:. DJANGO_SETTINGS_MODULE=rasiko_review_settings ../.venv/bin/python -m pytest --create-db`. These temporary files are not portable deployment configuration. Synthetic fixture accounts are confined to that DB.
4. Run Ruff, migration consistency, deploy/security/dependency checks, CSS build and docs guard. Do not overlap pytest runs sharing a test DB. One accidental overlap caused fixture collisions; both runs were stopped and the clean serial runs of 157 and then 159 tests passed afterward.
5. Finish release gates above, record actual results here and update README when guidance changes. The workspace has an empty protected `.git` directory, not a usable Git checkout; no commit/baseline diff was available and no PR was created.

## 2026-10-09 — actual branded product photographs

User chose a real-brand starter catalog with demo prices, then requested all Bailley water products. Added 31 photographed products: Coca-Cola/Diet Coke, Thums Up, Pepsi, Kinley, Bisleri soda, Frooti, Appy Fizz, Amul, Red Bull, Real Activ, Tropicana, Minute Maid, Paper Boat, Maaza and Bailley. Bailley covers published water sizes 250/500 ml, 1/2/5/10/20 L plus Soda 300/600/750 ml. The three soda entries use Parle Agro's range photo, explicitly noted in alt text and product descriptions. Source image URLs are in `assets/starter-catalog/catalog.json`; real pack photos were downloaded and optimized to WebP, preserving transparency. Commercial reuse authorization is not asserted.

`seed_branded_catalog` requires explicit demo-price acknowledgement, reads bundled assets without network calls, and optionally deactivates only original fictional seed products/variants and affected combos. Existing orders remain stored. Reruns preserve owner-edited prices, stock and photos. Prices/stock/taxes/case sizes are demo values; nutritional/expiry claims are not copied. Cards label demo prices. Product photos use existing responsive derivatives. The local preview was switched from ephemeral in-memory storage to filesystem media, and the catalog was installed only in `rasiko_review`; no live database was touched. No migrations or production environment changes.

Visual inspection exposed grid images overflowing their fixed wells despite `object-fit`; card and product gallery photos now use bounded positioning so complete packs fit. CSS rebuilt with cache version 9. Verification and final browser evidence recorded below.

Verified this batch: 23 catalog/storefront tests passed (19 existing collectstatic-directory warnings), including repeat-import preservation, historical demo retention, photo/srcset coverage and all seven Bailley water sizes. Ruff check/format passed (182 files); CSS build and documentation guard passed. Browser verified complete pack containment (card/photo both 148 px), loaded photographs, 10 Bailley entries at 390 px without horizontal overflow, and the 1 L product detail at 320 px with a loaded bounded image and no page overflow. Evidence: `docs/audit/product-photos-before.jpg`, `product-photos-desktop.jpg`, `bailley-products-mobile.jpg`, `bailley-product-detail-mobile.jpg`. Full prior payment suite was not repeated for this catalog batch. Live supplier stock/prices, tax/case configuration, jar deposits and image-use approval remain owner launch tasks.

## 2026-10-09 — Whole-box sales and owner Bailley availability

Implemented: customer quantity means whole boxes; variants with fewer than two units are unavailable (including cart/checkout/combo stock checks). Responsive card buying controls wrap within narrow cards. Dashboard variant forms require bottle volume in ml and at least two bottles per box; CSV entry validates both and exports volume. Cards explicitly label prices per box. Historical order snapshots and bottle inventory stay unchanged.

Owner-approved provisional demo sizes: 24 units up to 600 ml, 12 units through 1 L, six above 1 L. Manifest retains bottle reference prices and calculates box prices once. Ordinary starter imports preserve edits; explicit `--configure-demo-boxes` resets only starter box settings/prices/availability, preserving bottle stock. Applied solely to isolated preview PostgreSQL. No schema migration.

Bailley water: purple 250 ml/500 ml/1 L and separate pink Bailley One 1 L photo sourced from the Aditya Agro franchisee storefront (provenance in manifest). 2 L/5 L/10 L/20 L records inactive, history retained. Soda range remains active. 32 starter records, 28 active. Demo price/tax/supplier case verification and photo reuse authorization remain launch prerequisites.

Browser verified at 390 px and 320 px without horizontal overflow. Cart confirmed quantity 1 = 24 × 500 ml at ₹240 per box. Evidence: `docs/audit/bailley-boxes-mobile.jpg`, `bailley-boxes-desktop.jpg`, `box-cart-mobile.jpg`. Previous screenshots document pre-box configuration. Regression checks in progress; results recorded below before handoff.

Verification results: initial whole-suite run collected 163 tests: 152 passed and 11 failed (old single-bottle inventory expectations, CSV columns, dashboard minimum validation). Corrected explicit dashboard validation and the test fixtures/expectations. Affected regression rerun: 46 passed, one concurrency setup failure; fixed that test to submit eligible two-box orders against six bottles (two bottles per box). Final concurrency rerun passed (1 passed, 6.43 s). Thus all 47 affected checks passed across the final runs, including two new checkout/snapshot tests added after initial collection. Targeted Ruff and formatting checks, CSS build and documentation guard passed. Warnings: local staticfiles directory absent and outdated Browserslist database. A clean whole-suite rerun after these corrections was not performed; prior unchanged checks passed in the initial run. External production release gates from earlier batches remain open.


## 2026-10-09 — Git main handoff

Prepared all application, configuration, migration, photo, audit and documentation changes against GitHub main at `6a7f462` in a clean temporary checkout because the original workspace `.git` is empty/read-only. Excluded local environment credentials, SSH keys, database export, uploaded media, dependency folders and runtime caches. Added ignore rules for the local database export and SSH directory. Prior verification results and production gates remain as recorded above; committing does not verify deployment.

## 2026-10-10 — Oracle ARM translation build fix

User's first ARM64 build reached translation compilation, then failed with `ModuleNotFoundError: config` from the standalone django-admin executable. Changed Dockerfile to run collectstatic and compilemessages through `python manage.py` in one RUN, exporting generated temporary secrets only for that build step. This also prevents the following command from losing the temporary credentials required by production settings. Production configuration and migrations unchanged.

Verified Gujarati/Hindi compilation locally with production settings and temporary non-production credentials; command exited 0. Local runtime is Python 3.10, not production Python 3.12. Full corrected ARM64 image build remains to be verified on the user's Oracle VM. Updated README troubleshooting; documentation guard and whitespace checks run before commit.


## 2026-10-12 — Complete existing Razorpay Standard Checkout

Implemented locally: added authenticated, CSRF-protected POST create-order and JSON verify-payment routes under the existing payment order URL. Totals come from the owned shop order (minimum 100 paise); provider orders are reused. Checkout now starts on button click, handles missing SDK, creation errors, modal dismissal, failed payments and uncertain verification. Verification requires all three callback fields and the stored provider order identity; existing HMAC, captured status, amount/currency and idempotent fulfillment checks remain in place. Legacy return route and Stripe flow retained. No database migrations or dependency changes: Razorpay SDK was already installed.

Configuration: optional server environment Razorpay keys override dashboard keys only when both are supplied. Existing saved enable/disable state wins; the environment enable flag applies when no integration row exists. Historical processing retains credential access. Supplied test credentials were written only to the ignored local `.env` with mode 0600, with environment fallback activation disabled; no secrets recorded here. README and environment template now describe this precedence and testing. Test settings clear environment keys to prevent accidental external use.

Verified: all 51 payment tests passed against a fresh isolated PostgreSQL 14 cluster (Python 3.10 local runtime), including invalid signatures/order identity, uncaptured and mismatched payments, endpoint ownership/minimum/auth errors, reuse and configuration precedence. Existing warnings concern the absent local collectstatic output. Node harness executed the actual Checkout JavaScript and passed success, cancellation, payment failure, unavailable SDK, creation error and uncertain-verification cases. Final formatting/lint/documentation checks recorded below.

Remaining: no actual Razorpay API calls or browser sandbox transactions were made; tests mock provider responses. Real capture settings, webhook delivery, provider approval and method eligibility need account-side verification. Oracle deployment is unchanged. Next session: read this file and README, run the payment tests against isolated PostgreSQL, deploy deliberately, then verify a test-mode checkout and webhook before accepting live payments. Credentials shared in chat should be regenerated before subsequent use.


Final checks for this batch: targeted Ruff lint and format checks passed; JavaScript syntax and behavior harness passed; documentation guard passed. After adding explicit CSRF, GET-without-provider-creation and provider-outage coverage, all 19 Standard Checkout tests passed against isolated PostgreSQL (22.01 s). The first rerun could not connect under the restricted sandbox; rerunning with loopback access resolved the environmental failure. The preceding complete payment suite passed 51 tests before these three additional cases. No real provider transaction or production deployment verified.

Known configuration UI limitation: dashboard credential fields and their connection-test form describe saved dashboard values; environment overrides are documented in README and applied by checkout/historical processing. When managing keys through the environment, verify the actual sandbox checkout rather than treating the saved dashboard connection-test result as proof of those overrides.


## 2026-10-12 — Local app startup for owner integration setup

Started the development server on 127.0.0.1:8001 using the existing local PostgreSQL database and Redis. Initial storefront HTTP 500 identified pending schema migrations; applied catalog 0004, core 0002, orders 0004/0005 and payments 0002/0003 to the local database only. Storefront and dashboard login redirect destination then returned HTTP 200. No Oracle changes, seeds or credential updates. Server is a development process and must be restarted if the session ends. Actual authenticated integration setup and sandbox payment remain owner verification tasks.


## 2026-10-12 — Local stock restoration and shared-network login fix

Root causes: the only available local PostgreSQL database was the older fictional single-bottle demo, not the prior photographed review database. It had 30 active products and all active variants had units_per_box=1, so the whole-box availability policy correctly blocked them. Owner-approved branded starter catalog restored locally with explicit demo-price, fictional replacement and box-configuration options: 32 starter products, 28 active sellable variants, existing historical products/orders retained. No production database or real stock changed. Owner must verify actual supplier stock/prices before live selling.

Authentication: separate IP and username Axes buckets could lock unrelated customers sharing a network. Changed to a combined IP/normalized-email lockout while retaining five-failure/hour protection. Login IP throttle allows 60 POSTs/minute alongside that stricter account bucket. Login form lowercases email before Axes authentication; email backend also accepts legacy mixed-case stored email. Local stale attempts were cleared and the development server restarted on 127.0.0.1:8001. No passwords or account roles changed. Inspection confirmed the local owner's existing password differs from the bootstrap environment password; bootstrap does not reset existing users. README gives an interactive local owner reset command and explains local/Oracle account separation. SMTP/password-reset delivery remains unverified.

Verification: initial account/catalog/order run had 64 passes and one outdated checkout test expecting provider creation on GET. Updated that journey to assert GET does not create an order and the authenticated POST returns public provider data. Final isolated PostgreSQL run: 65 passed (15.03 s), including real Axes enabled lockout isolation, uppercase/legacy-email login, signup/logout, stock, cart and checkout regressions. Local collectstatic-directory warnings remain. Ruff lint/format passed. Browser confirmed active box buying controls, Bailley 500 ml in stock as 24 bottles/box, and one six-bottle Coca-Cola box added at the correct demo total; removed the test cart item afterward. Evidence: docs/audit/local-bailley-stock-recovery.png and local-box-cart-recovery.png. Initial screenshot local-catalog-recovery-before.png shows the initial hero only; pre-restoration product unavailability was confirmed by browser accessibility state and database inspection, not that screenshot.

Remaining: user must enter a known local account password or reset it interactively; actual owner sign-in/2FA and Razorpay account setup are not claimed verified. No Oracle deployment performed. No whole-site production certification is claimed; external payment, SMTP, backup/restore and performance gates documented earlier remain. Resume using the local dev server and current database rather than assuming the previous review DB survived.


## 2026-10-12 — Razorpay blank authentication popup investigation

User screenshots show Standard Checkout in test mode, a generic failure and a blank about:blank card authentication window. Local reported shop order remained pending; read-only Razorpay order-payments API inspection found two card attempts in created status with no provider error code/reason. This supports incomplete authentication, not a confirmed bank decline. No charge/capture/refund was initiated by the agent. Exact browser console cause remains unavailable.

Implemented: checkout response alone now sets COOP same-origin-allow-popups (supported for payment popup integrations); other site responses keep same-origin. This fixes a potential opener compatibility defect but is not proof it caused the supplied screenshots. Failure handler now displays whitelisted error code/reason labels without metadata/payment IDs, and pay.js cache version increased to 3. Restarted local development server on port 8001. Updated README with current official Indian test card and mock-bank instructions. No credentials, schema, production settings or Oracle changes.

Verified: 19 isolated PostgreSQL Standard Checkout tests passed, including checkout policy exception and unchanged home-page policy. Node checkout harness and JS syntax passed; diagnostic-label tests reject unsafe values and metadata. Ruff lint/format passed. Documentation guard run before handoff. Real sandbox authentication completion after this fix remains user verification; do not claim payment success from these checks.


## 2026-10-14 — Document Oracle SSH access

Added owner-requested laptop-to-Oracle SSH instructions to docs/projects_secret.md: existing key path, restricted file permissions, last confirmed instance IP, host verification, server project folder, service/log commands, disconnect and troubleshooting. Added README link. No credential contents copied, server connection attempted, deployment or application changes. Verified referenced local key file exists without reading its contents; documentation guard passed. Oracle reachability and current public IP were not independently retested.

## 2026-10-23 — Resume marketplace completion and release verification

Implemented source from the preceding session includes brand-scoped Heads, seller operations, versioned rider APIs, Flutter native projects, fulfillment checkout, dispatch and ledger work. The resumed source additionally contains provider linked-account onboarding/recovery, transfer settlement reconciliation and refund reversal records; expiry batches and FEFO allocation; seller invoice snapshots/PDFs; scoped support cases; operational alerts and retention settings. Catalog migration 0006 and marketplace migration 0004 introduce the new operational data. All feature switches still default off.

Verification in progress: yesterday's temporary runtimes and interrupted command outputs did not survive. Recreating temporary Python, Flutter, JDK17, Android SDK and isolated PostgreSQL tooling; no interrupted tests or APK build are claimed successful. User confirmed acceptance of Android SDK terms and has Android hardware; Firebase/APNs and iPhone testing remain unavailable. Existing shop/production databases and provider accounts are not modified by this verification.

Current fixes: provider settlement amounts remain immutable once a transfer exists; transfer funding checks include undelivered teams; marketplace buyers use seller invoices rather than the legacy platform invoice; readiness checks use the actual territory schema. Full affected tests and build results will be recorded below. Native signing, physical-device notifications/background behavior, provider sandbox Route approval/onboarding and commercial tax/legal configuration remain external gates.


Verified on 2026-10-23: 135 affected marketplace/payment/inventory/order tests passed on isolated PostgreSQL 14 with UTF-8 (253.99 s). An earlier run had 131 passes and an invoice failure caused by SQL_ASCII in the temporary test cluster; corrected the test-cluster encoding, without touching live data. Flutter 3.29.3 analysis found no issues; both multilingual widget tests passed. Hindi/Gujarati gettext compilation, targeted Ruff lint/format and documentation guard passed. A synthetic seller invoice was rendered with system Poppler and visually inspected: Hindi/Gujarati names render using embedded Noto fonts and shaping. Shortened the quantity heading after visual review. Native Android Gradle build is still running; no APK, signing or phone result is yet claimed.

Additional code: failed Celery jobs create admin-only alerts containing only job IDs; successful completion of the same job resolves the alert. Monitoring does not silently clear failed-job alerts. Added a regression for this behavior; its post-change test result will be recorded after the isolated PostgreSQL recovery. Business/onboarding links were moved to their correct seller-team context (they previously used an out-of-scope team variable in rider rows). Updated owner guide and README to describe actual onboarding, settlement/reversal, invoice, batch, retention and recovery behavior. Broader pre-existing untranslated storefront strings are still outside the new translated operational strings; full language acceptance is not claimed.

## 2026-10-24 — Continue interrupted native build and final operational checks

The 135-test result and Flutter analysis/widget results from 2026-10-23 are recorded above. Temporary SDKs/processes did not survive another interruption; APK completion remains unverified. Restoring build/test dependencies under the workspace's sibling `.rasiko-tools/` directory so future resumes retain them. This directory contains development runtimes and disposable isolated data, not production keys.

Scoped product-photo upload is now connected to seller product management: allow-listed images are verified, resized/re-encoded, stripped of metadata and rendered into responsive copies using the existing image pipeline. Added an upload/scope regression. Failed-job alerts and latest invoice/UI fixes still need the final targeted rerun. No production migrations, provider account mutations, deployment, Firebase setup or physical-device testing performed.

Verified on 2026-10-24: the final operational regression set passed 12 tests in 41.86 s on a newly created isolated UTF-8 PostgreSQL 14 cluster, including photo re-encoding/scope and failed-job alert persistence. Targeted Ruff lint/format, Bandit, Django check, migration consistency and documentation guard passed. Flutter analysis and both widget tests passed again inside the persistent build helper; native Gradle compilation remains in progress.

Browser verification used disposable local owner/seller data and completed password plus actual TOTP login, marketplace navigation, seller-team business/onboarding link checks and Hindi onboarding rendering. Found and displayed previously calculated refund/delivered/cancelled counters. Evidence: docs/audit/marketplace-metrics-before.png and marketplace-operations-after.png. Reviewed fuzzy Hindi/Gujarati operational translations so gettext activates them. Replaced raw onboarding status/enum values with translated human labels and disabled saved-credential autofill for PAN/bank inputs. No provider forms were submitted and no real seller/bank details were entered.

Final UI follow-up on 2026-10-24: confirmed corrected Hindi and Gujarati onboarding labels, translated business-type choices and human onboarding status through the real browser. Saved docs/audit/marketplace-onboarding-gujarati.png. The scoped portal smoke regression passed after these changes, and migration consistency remains unchanged. Android build progressed to installation of required NDK 26.3.11579264 under the accepted SDK licence; completion/phone behavior is still not asserted until the APK exists and is checked.


## 2026-10-24 — Project-local mobile build resource limits

Owner requested a low-resource profile for an 8 GB / four-thread Ubuntu laptop and explicitly prohibited interrupting the current build. Updated only Rasiko Android Gradle properties: maximum two workers, parallel execution off, heap 1536 MB, metaspace 512 MB, code cache 128 MB, Kotlin in-process and no persistent idle daemon for future invocations. The already-running build retains its startup settings; it was not stopped, restarted or reprioritized.

Updated the Ubuntu helper to use a project-local nonblocking lock, detect existing Rasiko Flutter/Gradle processes, run steps sequentially at lower CPU/disk priority and run Flutter tests with concurrency one. Lock files are ignored. Source functionality and global Gradle/OS configuration are unchanged. No new heavy build was started to validate this profile while the earlier build remains active. Lightweight validation and final build result are recorded below.

Resource-profile validation: Bash syntax and a real lock-contention check passed. With the project lock held, the helper exited before any Flutter/Gradle invocation. Documentation guard passed. No new heavy build or daemon was launched for these checks, and the active build was left untouched. The 1536 MB profile still requires validation on a subsequent build; current build output retains its original startup limits.

Enabled Gradle task caching in the same project-local profile to reduce repeated compilation; configuration cache and global Gradle properties remain unchanged.

Added `-XX:ActiveProcessorCount=2` to the same future Gradle JVM profile so JVM GC/library thread pools also size for two processors. Validated JVM option recognition with `java -version` only; no build or daemon was started for this check.

The pre-existing native build finished by itself with CXX1416 (Ninja missing); it was not interrupted. Installing SDK CMake 3.22.1 locally provides Ninja. Added helper preflight/PATH handling so future builds fail early if this tool is missing. One sequential native retry will use the new low-resource profile; previously passed Flutter source/widget checks are not repeated for this tool-only repair.

Low-resource retry startup verified in the real Gradle log: `-Xmx1536m`, `-XX:ActiveProcessorCount=2`, two worker leases and local task caching are active. CMake/Ninja installation completed. Retry runs sequentially under nice 10 / best-effort I/O priority 7, with the project lock held. Global Gradle properties contain no overriding resource keys and were not edited. The previous build finished on its own before this retry started.


Final Android build on 2026-10-24: **BUILD SUCCESSFUL in 2m 20s**, 276 tasks (111 executed, seven from cache, 158 up-to-date); Flutter reported the debug APK built successfully. Verified actual JVM startup `-Xmx1536m`, `ActiveProcessorCount=2` and two worker leases; task caching active. New build ran at reduced CPU/disk priority and held the project lock. Existing build was not interrupted: it had exited with missing Ninja, which was then installed via SDK CMake 3.22.1 before the only retry. App code/functionality and global settings were preserved.

Artifact: artifacts/rasiko-rider-debug.apk (~190 MB), SHA-256 c25f8bdd620e3400e68aa8cf0c1c9cd64b448607497c8325df35c74b2874f39f. Development server origin is https://rasiko.in; Firebase push remains off. The app still needs backend deployment/configuration and physical Android acceptance; Firebase/APNs, IPA signing/iPhone checks and real Route sandbox acceptance are not claimed complete. Build warnings: plugin NDK declarations recommend 27 while this build used 26.3, and pinned Gradle plugins use APIs deprecated for Gradle 9. These did not fail the debug build. No release/store readiness is implied.

APK verification passed: Android apksigner verifies v1/v2 signatures; package is in.rasiko.rasiko_rider 0.1.0 (versionCode 1), min SDK 23, target SDK 35. ZIP inspection confirms the rider alert sound and arm64 native libraries. Verification/package metadata and SHA-256 files are saved beside the APK under artifacts/. Physical installation/runtime behavior was not tested. The resource-limited native build is complete; no second heavy build was run concurrently.


## 2026-10-24 — Authorized local database upgrade and startup

Owner explicitly approved backup and migration after the local homepage failed with missing catalog_product.seller_team_id. Confirmed configured database is localhost PostgreSQL 14. Created a private custom-format backup under ../.rasiko-tools/backups/rasiko-before-marketplace-20261024-175002.dump (304408 bytes, mode 0600), and verified its archive table of contents with pg_restore --list before applying changes. Actual migration plan contained seven pending migrations (earlier response incorrectly said eight); all seven applied successfully. Django system check passed. Existing local development server remains on 127.0.0.1:8001; verified homepage HTTP 200 and unauthenticated partner portal HTTP 302. No seed, marketplace backfill, provider calls, production deployment or mobile build performed. Marketplace switches and existing records were not intentionally changed beyond schema migrations. Celery worker/scheduler were not started as part of this startup.


## 2026-10-24 — Head setup selection clarity

User recording showed confusing native brand multi-select and blank territories. Read-only local inspection confirmed 21 existing brands including Bailley and zero territories. Replaced Head brand/territory multi-select lists with checkbox groups, added account/selection help and a missing-territory message linking Add area. Preserved model validation and permissions; no accounts, brands or territories created. Restarted only local web server on port 8001. Ruff passed; rendered form assertions verified checkbox widgets and missing-territory link. Browser checked Bailley checkbox toggles in an account-free rendered preview; no Head submitted. Before evidence extracted from user screencast: docs/audit/head-multiselect-before.png; browser after: docs/audit/head-checkboxes-after.png. New guidance is gettext-marked; Hindi/Gujarati translations for these added sentences remain pending.


## 2026-10-24 — Head-managed seller brand permission

Implemented requested distinction: independent sellers can have multiple active brands; a seller with any active Head-managed team needs explicit admin multi-brand permission before another brand becomes active, or before an existing multi-brand seller joins a Head. SellerTeam saves lock the seller row and validate competing active teams; model/form validation rejects conflicting creation, attachment and reactivation. Permission removal rejects unresolved active multi-brand Head teams; inactive histories remain. Admin-only Seller verification form exposes allow_multiple_brands; existing verification view retains owner checks and auditing. One brand already supports multiple Heads through a many-to-many relation, now covered by regression. Existing jurisdiction/exclusive territory rules remain.

Migration marketplace.0005 added the default-false permission. Applied locally under prior explicit local backup/migration authorization after verifying private backup rasiko-before-brand-permission-20261024-180828.dump. No production update, invented team grants or provider call. Local server restarted on port 8001. Two new isolated PostgreSQL tests passed; existing suite initially caught three fixtures that implicitly assumed unrestricted Head multi-brand sales. Those three now explicitly grant the required admin permission, retaining their scope/suspension/checkout assertions. Combined new and existing marketplace tests: 34 passed. Django check and Ruff passed; final docs guard below.

Admin control visually checked with account-free browser preview, evidence docs/audit/seller-multiple-brands-after.png; no seller submitted or permission granted. Before screenshot for this newly added control was not captured (earlier Head selection screenshots are a different screen). New UI strings use gettext but their Hindi/Gujarati translations remain pending. Owner guide and README explain permission and territory setup. Physical device and production release gates remain unchanged.


## 2026-10-24 — Rider registration HTML response diagnosis

User phone screenshot shows raw JSON FormatException with an HTML response. Credential-free endpoint checks confirmed deployed https://rasiko.in/api/v1/rider/login/ returns HTTP 404 text/html, whereas local port 8001 endpoint returns HTTP 403 application/json (marketplace remains gated). Installed APK targets rasiko.in; a local invitation cannot register against that separate server. No credential/invitation from screenshot replayed. ADB inventory found no connected phone. USB local test versus deployed backend path awaits user clarification; production was not deployed or modified.

API client now catches malformed/HTML responses and reports server host/status and setup guidance without leaking response HTML. Rejects non-object JSON and preserves normal API errors and successful responses. HTTP client/base URL injectable for tests. Five Flutter tests passed (three API regressions and two existing language/widget checks), with concurrency one. Initial sandbox test socket denial was resolved by permitted local socket execution. Analyzer warning on redundant type check fixed; final analyzer result below. Existing APK has not been rebuilt/replaced; source fix alone does not make missing deployed endpoints work. No new native build or device registration performed.


## 2026-10-24 — Samsung M14 USB-local Rider build

User connected Samsung M14 and requested local registration continuation. Initial ADB inventory showed no phone; provided Samsung Developer options/USB debugging and authorization steps. Preparing a separate USB-only debug APK: explicit RASIKO_USB_LOCAL_TEST plus kDebugMode permits only http://127.0.0.1:8001; debug-only Android network configuration allows cleartext only to loopback. HTTPS remains required in release builds. Build helper preserves existing default artifact and writes rasiko-rider-usb-debug.apk for this profile, under unchanged serialized two-worker/1536 MB/nice settings.

Enabled only local MarketplaceSettings.enabled for requested registration testing and recorded audit event; dispatch and payouts remain false. Local Rider API now returns HTTP405 JSON on GET login (POST required), confirming route/gate readiness without using credentials. Six Flutter tests passed, including explicit loopback opt-in rejection, malformed responses and existing multilingual widget tests. Analysis passed. Build completion, signature and device/USB results recorded below; no physical phone success claimed at this point. No production changes, credentials replayed or LAN exposure.


USB APK result: build succeeded in 113.9 seconds; artifact artifacts/rasiko-rider-usb-debug.apk (208 MiB), SHA-256 2c78113996459d70f205c814cb6bebc1e0aef9b7afd63793e2a9e40de34c2230. apksigner verification exited successfully; checksum saved alongside APK. All six tests and analysis passed in serialized helper. Default HTTPS artifact preserved. User enabled USB debugging, but repeated ADB inventories still show no device and lsusb shows no Samsung/Android hardware. Installation, adb reverse and physical registration remain blocked on USB data detection/phone authorization, not claimed complete. No live backend deployment.


## 2026-10-24 — Rider list-response regression on phone

Phone user reported Invalid Rider service response after USB connectivity restored. Found prior malformed-response guard incorrectly rejected valid list JSON: offers and deliveries endpoints return lists immediately after login/register. Fixed guard to accept maps/lists while rejecting scalar responses and HTML; normal API errors remain. Added list endpoint regression and changed scalar rejection test accordingly. Read-only local count shows one active rider exists, consistent with registration completing before refresh failed. No passwords/tokens inspected or replayed. USB mapping present. Updating APK via serialized low-resource helper; saved login remains intact because no app data clear/uninstall is used. Final build/test/device-copy results below.


Rider response-fix build succeeded in 68.8 seconds under existing low-resource profile; analysis and all seven Flutter tests passed. SHA-256 a51f503193e5d6592b843653872f1d513d545ef18f7307bbbe79d3fc0e17fbc5. Copied successfully to Redmi Download/Rasiko-Rider-USB-Test-Fixed.apk for manual in-place update (MIUI had blocked ADB installation). USB reverse restored. User reports rider dashboard showing location consent, online toggle, available deliveries, own deliveries and sign out: physical registration/sign-in confirmed by user. Corrected APK installation/refresh and delivery/notification behavior still await user checks.

## 2026-11-09 — Seller-owned shops and GitHub review preparation

Implemented seller shop workspaces using the existing seller identity, so registration creates a private shop without duplicating business/rider/financial ownership. Applications accept multiple brands and areas; each brand starts inactive and each brand/area combination creates an approval request. Added seller/admin-only shop profile management (name, plain-text description, publication preference), setup overview and links to existing catalog/stock/import, orders/income, onboarding/invoice/support and rider invitations. Sellers can request another brand plus service areas; team activation and territory approval remain privileged. Existing admin multi-brand permission for active Head-managed sellers is retained; independent sellers and Heads can have multiple brands/regions. Publication defaults off, including existing sellers.

Public shops require marketplace enabled, active owner, active verified seller, publication and effective service assignment for an operational brand team. Public product queries include only those eligible teams and paginate 24 products. Public context contains no private bank/financial/Head identity fields; user content is escaped. New shop pages show standard delivery/address validation instead of the global Rajkot free/fast banner. Migration marketplace.0006 adds description/publication fields. Only isolated disposable PostgreSQL databases were migrated; real local shop and production databases were not changed this session.

Added regressions for multi-brand/multi-area application, shop ownership and forged approval/payment fields, public visibility/escaping, admin exception on brand requests, multi-state Head grants and Rider registration/token/heartbeat/offer-history compatibility. Five initial new shop tests and 51 marketplace tests passed before the final multi-state/banner additions. Broader baseline run reached 100% passing output, but its shell session reported SIGTERM; not treated as a reliable successful exit. Repeating final affected suite after dependency updates with JUnit output; final results recorded below.

Used pre-push audit and UI/UX skills. Scoped Ruff lint/format and marketplace Bandit passed; Django check and migration consistency passed. Browser used synthetic isolated data, real password/TOTP authentication, compared existing network dashboard with the new shop page, opened the buyer shop and verified Gujarati labels at actual 390px viewport (document scroll width375, no horizontal overflow). Evidence: docs/audit/seller-workspace-before.png, seller-shop-after.png, seller-shop-gujarati-mobile.png. Added/compiled 37 Hindi and Gujarati shop translations; old storefront translation backlog remains as documented.

Dependency audit initially found vulnerable existing development/runtime packages. Verified stable releases and updated REST framework3.18.3, Autobahn26.10.1, Twisted26.10.0, Pillow13.0.0, Black26.10.1; requests pinned2.34.2. Updated only project virtualenv (including pip26.3). Final installed-environment pip-audit exited0 with no known vulnerabilities; pip check passed. No claim of exhaustive production security certification.

The supplied workspace had empty read-only Git metadata and no usable history. Created separate review checkout ../.rasiko-review from confirmed Satyajeetsinh-jadeja111/RASIKO main 72e7a6a, branch seller-shop-workspace. GitHub connector reads work but branch write returns403; CLI token invalid. Existing SSH authentication succeeded for the intended account, so publication uses SSH. Prior marketplace/native source is absent from main and must be included for a runnable review. Snapshot excludes private setup-guide changes, env/secrets, media/databases, SDKs, build output, APKs and unrelated screenshot history. No main push, live deployment, provider call, mobile build or phone change this session. Final commit/push/review link and verification outcomes follow below.


Final verification on 2026-11-09: 151 affected backend tests passed (219.583 s, zero failures/errors/skips, JUnit saved privately); final six shop-specific checks passed after the last multi-state Head/banner changes. These six overlap five tests in the broader set and are not six additional distinct tests. Full-source Ruff lint/format, marketplace Bandit, Django check, migration consistency, pip check and documentation guard passed. Installed dependency audit exited0 with no known vulnerabilities. Actual browser confirms translated Gujarati status/checklist at390px without overflow and approved buyer shop rendering. No native rebuild or new physical phone test was needed for these backend/UI changes.

Review snapshot contains 179 changed/new files, including the earlier marketplace and Android/iOS source not yet in GitHub main. No detected private-key or generated candidate files; whitespace errors in bundled font licenses removed without changing license wording. Target review branch: seller-shop-workspace; publication uses existing authenticated SSH. Production deployment remains explicitly deferred until review and staging/provider/device acceptance.
