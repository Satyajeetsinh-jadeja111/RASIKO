# Rasiko — project handoff

Last updated: 2026-10-09. Read this file first, then README.md, AGENTS.md and docs/audit/REPORT.md.

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
