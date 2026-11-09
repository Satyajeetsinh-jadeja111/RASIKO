# Rasiko implementation audit — 2026-10-09

This is evidence from an isolated demo shop, not approval to launch the production shop. No live database, provider credentials or Oracle host was changed.

## Fixed and observed

- Empty search illustration was approximately 644 px high in the original mobile capture. The shared empty state now caps it at 80 px on mobile and 96 px from 720 px. Before: `01-search-before.jpg`; after: `02-search-after-390.jpg`.
- Empty search uses product-neutral copy and recovery actions. Clear filters retained `q=lassi` and restored six demo results. A rating filter produced the bounded empty state through HTMX; `aria-busy` returned to false (`htmx-empty.jpg`).
- Mobile filters collapse; desktop filters open. Shared focus, loading, disabled, input, touch-target, reduced-motion and wrapping rules added. Header and chat branding remain proportional.
- All 29 dashboard navigation destinations were captured. The original mobile navigation forced a 3,232 px page width. Grid minimum sizing fixes this. Slider cards and delivery hours needed additional responsive layouts/contained table scrolling.
- Final six-width sample (320, 375, 390, 768, 1024, 1440): search, product, account, dashboard slider, delivery, products and integrations had no page-level horizontal overflow. See `route-widths.json`. Other dashboard destinations were checked at 390 px in `dashboard-final.json`; the two initially failing routes are superseded by the six-width checks.
- Mobile customer captures cover home, brands, product, offers, cart, help, tracking, bulk quote, privacy and account. See `mobile-public.json` and `mobile-*.jpg`. Gujarati and Hindi navigation/product text fit at 390 px; translation completeness is not certified.
- Synthetic browser COD journey: product → cart → minimum-order disabled state → checkout → placed → confirmed → packed → out for delivery → delivered with delivery code. Evidence: `cod-success.jpg`, `staff-delivered.jpg`. A synthetic manual cash refund after COD collection succeeded and was confirmed on the recovered staff page (`staff-refund.jpg`). Refund safety checks now reject uncollected payments and prevent over-refunding after partial refunds.

## Verification and measurements

- Final clean serial regression suite: 159 passed (66 warnings about the absent development collectstatic directory). Earlier targeted stock/cache checks: 10 passed, including concurrent last-stock competition. Image/cache/privacy-header suite: 3 passed; all tests are included in the final full suite.
- Ruff source checks/formatting, Django migration consistency, production `check --deploy`, Bandit, isolated Nginx TLS/static/proxy configuration and synthetic Compose configuration passed.
- Backup tests: failed dump and failed upload return failure without a success marker; successful SQL dump restored with `ON_ERROR_STOP=1` into a separate database, and synthetic media archive content matched.
- Warm demo queries: home 20 → 1, search 11 → 9, empty search 8 → 6, cart 3 → 1. This measures query count, not production latency.
- Local DEBUG/Django-client load: 20 browsing + 5 checkout-page users, 300 requests, all HTTP 200. Browsing p95 2,334.8 ms; checkout-page p95 1,914.8 ms. See `local-load.json`. This fails the 300 ms target and is not an Oracle/network benchmark. It does not submit concurrent paid orders; separate transaction tests cover payment-start races and stock competition.

## Prioritized remaining acceptance

| Priority | Requirement | Status / next action |
| --- | --- | --- |
| P0 | Provider sandbox and live readiness | External prerequisite: approved test accounts, selected gateway credentials, HTTPS webhook endpoint and Razorpay capture confirmation. Exercise real checkout/refund/reconciliation before live mode. |
| P0 | Oracle production latency | Unverified: provision the approved A1 entitlement, release image and representative catalog; measure 20 browsing + 5 actual checkout users. Target p95 <300 ms remains unmet locally. |
| P0 | ARM64 image | Local build blocked by absent emulation (`exec format error`); QEMU-backed multi-architecture CI added but not run here. Native build status is recorded in project.md. |
| P0 | Off-server recovery | Local restore passed; remote destination, encryption-key recovery, real media recovery and production rollback drill remain prerequisites. |
| P1 | Full state/accessibility matrix | Route captures are not exhaustive proof of every loading/error/permission/modal/editor state. Complete keyboard/screen-reader, contrast, 200% zoom, long text, all CRUD/detail routes, subscriptions, review submission, chat ticket and online payment states before release. |
| P1 | Mobile Lighthouse >=90 | Not measured. Run on the production-like HTTPS Oracle release with real product imagery and mobile throttling. |
| P1 | Translation completeness | Existing storefront/staff copy mixes translated and English strings. Newly shared empty search copy has Gujarati/Hindi translations; audit all catalogs and long text separately. |
| P2 | Catalog/media maintenance | Run `build_responsive_images` for pre-existing uploads. New uploads generate derivatives automatically. Monitor stale/unreferenced image storage during future cleanup. |

The remaining checks are explicit limitations, not claims that the full acceptance plan is complete. README describes operations; project.md is the session handoff and records exact implementation and migration status.

## 2026-10-09 — product photo follow-up

The user selected actual branded starter products with demo prices and requested Bailley. Replaced the isolated preview's 30 fictional active products with 31 photographed starter products across 15 brands; original records/order history are retained as inactive. All seven Parle Agro published Bailley water sizes plus three soda sizes are present. Soda entries use an explicitly described official range photo. Provenance and limitations: `assets/starter-catalog/README.md` and `catalog.json`.

Browser confirmed loaded pack photos, fixed full-pack containment, mobile Bailley listing (10 products) at 390 px, and bounded loaded detail photo at 320 px without page-level overflow. Before/after: `product-photos-before.jpg`, `product-photos-desktop.jpg`, `bailley-products-mobile.jpg`, `bailley-product-detail-mobile.jpg`. Catalog/storefront regression suite: 23 passed, 19 existing missing-collectstatic warnings. CSS build, Ruff and documentation guard passed. Prior payment/Oracle acceptance limitations remain unchanged.

### Whole-box / Bailley stock follow-up — 2026-10-09

Owner selected provisional demo box counts (24 ≤600 ml, 12 through 1 L, six above 1 L). Cards/cart show full-box labels and prices. Single-unit variants cannot be purchased. Dashboard/CSV require bottle count and ml volume. Bottle stock and historical snapshots preserved. Bailley water active: purple 250/500 ml/1 L and pink Bailley One 1 L; other water sizes hidden; soda retained. Browser evidence: [mobile catalog](bailley-boxes-mobile.jpg), [desktop catalog](bailley-boxes-desktop.jpg), [one-box cart](box-cart-mobile.jpg). No page overflow at 320/390/1440 px. Responsive buying controls wrap within narrow cards.

All 47 affected catalog/dashboard/inventory/payment checks passed across final runs (46 passed, followed by corrected concurrency test passing separately); initial full run had 152 passes and 11 failures corrected in those reruns. See project.md for exact limitations. Production pricing, supplier case counts and photo reuse permissions still need owner review.
