# Rasiko — build plan (for approval)

Source spec: `RASIKO_CLAUDE_CODE_PROMPT_FINAL.md` (in rasiko-starter.zip). This plan follows it; changes and concerns are in section 7.

## 1. Architecture

```
            nginx (TLS, static/media, rate limit)
                 │
        ┌────────┴─────────┐
   gunicorn (WSGI)    uvicorn (ASGI: Channels, live chat + dashboard alerts)
        └──── Django 5 project "rasiko" ────┘
                 │            │
            PostgreSQL 16   Redis (cache, Celery broker, Channels layer)
                              │
                    Celery worker + celery-beat
          (emails, stock reservation expiry, reports, insights, backups)
```

- Server-rendered Django templates + Tailwind (theme tokens = Vijay Navagraha palette) + HTMX + Alpine.js. The static home page already built in `/mnt/project-files/rasiko/` becomes the base template.
- DRF only for AJAX endpoints (cart, search autocomplete, chat, delivery quote, webhooks).
- Integrations sit behind interfaces so they can be swapped: `PaymentGateway` (Stripe, Razorpay, COD), `DistanceProvider` (Haversine × road factor, OSRM later), `SmsProvider`, `WhatsAppProvider` (click-to-chat fallback), `AiAssistant` (Claude API, FAQ fallback).

## 2. Django apps

| App | Owns |
|---|---|
| `core` | Site/store settings (singleton), auspicious elements, muhurat mode, audit log, encrypted secrets, pages/policies |
| `accounts` | Custom User (email login, phone), roles (Owner/Manager/Staff), 2FA (TOTP), addresses, COD phone verification |
| `catalog` | Category tree, Brand, Product, ProductVariant, ProductImage, attributes, search, filters |
| `inventory` | Stock movements, reservations, low-stock alerts, Quick Stock |
| `cart` | Session/user cart, mini-cart, wishlist, recently viewed |
| `delivery` | Store location, service area (radius + polygon + pincodes), fee slabs and rules, slots, hours/holidays, riders, delivery economics |
| `orders` | Order, OrderLine, status timeline, OTP handover, invoices (PDF), reorder, subscriptions, bulk/party quotes |
| `payments` | Gateway interface, Stripe, Razorpay, COD, webhooks, idempotency, refunds |
| `promotions` | Coupons, combos, festival campaigns, hero slides, Rasiko Coins, referrals |
| `reviews` | Verified reviews, photos, moderation, "Rasiko Team" replies |
| `notifications` | SMTP settings (Fernet-encrypted), templates, admin/customer email toggles, email log, WhatsApp |
| `support` | Help Center FAQ, AI chat with server-side tools, tickets, support inbox (Channels) |
| `analytics` | KPIs, charts data, reports + exports, insights engine, competitor watch, what-if calculator |
| `dashboard` | The custom `/manage/`-style admin UI (URL configurable) |

## 3. Core data model (abridged)

- **Category**(parent, name, slug, image, sort, active) · **Brand**(name, logo, active)
- **Product**(name, name_gu, name_hi, slug, brand, categories M2M, veg, description, ingredients, allergens, nutrition JSON, shelf_life, storage, origin, attributes JSON, tags, featured, bestseller, seo fields, deleted_at)
- **ProductVariant**(product, label, sku, barcode, mrp, price, cost_price, gst_rate, hsn, weight/volume, stock_qty, low_stock_at, max_per_order, active) → out of stock automatically at 0
- **StockMovement**(variant, delta, reason, ref, user) · **StockReservation**(variant, order, qty, expires_at)
- **Address**(user, lat, lng, pincode, text) · **ServiceArea**(center, radius_km, polygon, pincodes) · **FeeSlab**(min_km, max_km, fee) · **DeliveryRules**(free thresholds, min order, small-order fee, surcharges, COD limit, road factor, cost inputs)
- **Order**(public UUID, user, address snapshot, slot, subtotal, discount, coins_used, delivery_fee, surcharges, gst, total, payment_method, status, rider, otp, placed_at…) · **OrderLine**(variant snapshot, qty, price, cost, gst) · **OrderEvent**(status, at, by)
- **Payment**(order, gateway, intent_id, amount, status, idempotency_key, raw) · **Refund**(payment, amount, lines, reason, status, restock, by)
- **Coupon**, **Combo**, **Campaign**, **HeroSlide**, **CoinLedger**, **Referral**, **Subscription**, **BulkQuote**
- **Review**(verified order line, stars, title, body, photos, status, reply)
- **FaqArticle**, **ChatSession/ChatMessage**, **Ticket** · **EmailSetting**, **EmailLog** · **AuditLog** · **CompetitorPrice**

All money as `Decimal` rupees (2 places, never float); all totals recalculated on the server; order state changes inside `transaction.atomic` + `select_for_update`.

## 4. Folder structure

```
rasiko/
  config/ (settings/base.py, dev.py, prod.py, urls.py, asgi.py, wsgi.py, celery.py)
  apps/<app>/ (models, services, views, api, tasks, templates, tests)
  templates/ (base, storefront, dashboard, emails)
  static/src/ (tailwind input, alpine/htmx components)  static/brand/
  locale/ (gu, hi)
  docker/ (nginx.conf, entrypoint, backup.sh)
  docker-compose.yml  Dockerfile  .env.example  pyproject.toml  README.md
  .github/workflows/ci.yml  .pre-commit-config.yaml
```

## 5. Phases (each: tests + lint + Docker run + Playwright click-through + commit, one PR per phase)

1. Skeleton, Docker, settings split, auth + roles + 2FA, Tailwind theme tokens, base layout from the approved home page, favicons + manifest
2. Catalogue models, dashboard CRUD, storefront browsing, search/autocomplete, filters, product page
3. Cart, checkout with Leaflet pin, service-area check, fee engine, COD, orders, stock reservation
4. PaymentGateway: Stripe + webhooks, Razorpay, GST invoices, refunds
5. Email settings, notification engine, all templates
6. Dashboard: Quick Stock, hero slider manager, orders, customers, coupons
7. Sales & finance analytics, charts, exports, insights engine, delivery economics + what-if
8. Reviews + growth features (Coins, referral, reorder, subscriptions, bulk orders, Thandu guarantee, WhatsApp, gu/hi/en, festival campaigns, suggestions, local SEO, competitor watch)
9. Help Center, AI chat with server-side tools, support inbox
10. Security hardening, performance, SEO/PWA, full test pass, independent security review, README

## 5a. Integrations page (owner's request, 2026-09-26)

Every paid or keyed service is **off by default** and switched on from Dashboard → Settings → Integrations. Each one has an on/off toggle; turning it on shows the fields for its keys, plus a "Test connection" button. Keys are encrypted at rest (Fernet), never shown again after saving (only "•••• last 4"), changes go to the audit log, and only the Owner can edit them.

| Integration | Fields | When off |
|---|---|---|
| WhatsApp Business (Meta Cloud API) | Phone number ID, access token, business account ID, webhook verify token, template names | Free click-to-chat "Order on WhatsApp" link to the shop's number; order updates by email only |
| Stripe | Publishable key, secret key, webhook secret | Hidden at checkout |
| Razorpay | Key ID, key secret, webhook secret | Hidden at checkout |
| Claude AI help chat | API key, model name | FAQ-matching bot answers instead |
| SMS OTP (e.g. MSG91 / Twilio) | Provider, API key, sender ID, template ID | COD phone check by email OTP |
| Email (SMTP) | Host, port, TLS, user, app password, sender, admin recipients | Emails queue in the log, not sent |
| S3-compatible storage (optional) | Endpoint, bucket, access key, secret | Local media storage |

Only a few secrets must stay in the server's `.env`, because the site needs them before the dashboard exists: Django `SECRET_KEY`, the Fernet encryption key, and the database and Redis passwords.

## 6. Test and quality gates

pytest-django + factory-boy, ≥80% coverage on orders/payments/stock/delivery/refunds, ruff + black, bandit, pip-audit, `manage.py check --deploy` clean, GitHub Actions CI on every PR.

## 7. Things to flag (the spec asks me to)

1. **Repository:** there is no Rasiko repo on your GitHub yet, and I can't create one. Please create an empty private repo (e.g. `rasiko`) and I'll build there.
2. **Scale:** this is a very large build. I'll deliver it as one reviewable PR per phase rather than one giant change, so you can check and merge as it goes.
3. **Payments:** Stripe India is invite-only, so Razorpay is built as an equal option (already in the spec). I'd make Razorpay the default until Stripe approves you.
4. **Things I can't finish for you:** real FSSAI/GSTIN numbers, Stripe/Razorpay/SMTP/WhatsApp/Claude API keys, the store's exact location and the Rajkot pincode list (I'll seed a list for you to verify), and the server/domain for deployment.
5. **WhatsApp Business API** needs Meta approval; click-to-chat links work from day one.
6. **Vastu layout** is followed as zones within normal shopping usability (logo top-left, cart top-right), as the spec says.
