# Build "Rasiko" — Food & Beverage E‑commerce for Rajkot (full‑stack, production‑ready)

You are a **senior full‑stack engineer and security‑minded architect**. Build the complete, production‑ready e‑commerce platform described below from scratch in this repository. Work like a senior dev: plan first, build in phases, write tests, commit after each phase, and never leave TODO stubs for the features listed here.

**How to work**
- Start in **plan mode**. Read this whole prompt, then show me an architecture plan, data model, folder structure and phase list before writing code. Wait for my OK, then build.
- Use any **skills, subagents and tools** you have (e.g. frontend/design skills for the UI, a separate review subagent for the security audit at the end).
- Track work with a task list. After each phase: run the tests, run the linters, run the app with Docker and click through it in a browser (Playwright) to check it really works, then commit.
- If something in this prompt is impossible or a bad idea, tell me and suggest the better option. Don't just silently skip it.

---

## 1. Brand

- **Name:** Rasiko   ·   **Tagline:** "Rajkot no swaad, tamare ghare." (English: "Rajkot's taste, at your doorstep.")
- **Logo and design reference files** are in `/brand` (`rasiko-home-preview.png`, `rasiko-vijay-palette.png`, `rasiko-logo.svg`, `rasiko-logo.png`, `rasiko-icon.svg`, `rasiko-icon-512.png`, `rasiko-mark.svg`). Use them for the header, favicon (generate all favicon sizes + `site.webmanifest` from `rasiko-icon.svg`), emails, invoices and the admin panel.
- **Colour theme: "Vijay Navagraha" palette, an all‑rounder theme chosen by Vastu Shastra and astrology to win the market.** Surya and Mangal bring victory over competition, Budh brings trade, Guru brings prosperity, and Chandra and Shukra bring trust and attraction. The colours of Shani, Rahu and Ketu (black, smoky grey, blue) are kept out. Use these exact names as Tailwind theme tokens:

  | Token | Hex | Vastu / planet meaning | Where to use |
  |---|---|---|---|
  | `kesari` | `#FB8C00` | Surya (Sun): victory, fame, leadership | The **"Vijay sunrise" gradient** (`kumkum → kesari → haldi`) on the hero accent word, "⚡ Rajkot's fastest" badges, #1/Bestseller tags and the footer top border. Accent only |
  | `kumkum` | `#E53935` | Mangal (Mars) / Agni: courage, beating rivals, food, energy | Logo, sale badges, chat bubble, active menu item, outline buttons |
  | `sindoor` | `#B71C2C` | Mangal: strength | Big headings (hero title), logo shade, hover of red elements |
  | `maroon` | `#7A1F2B` | South zone: weight, stability | Footer background (with a 5px `kumkum → kesari → haldi` gradient top border), section titles in the SW block |
  | `tulsi` | `#2FA05A` | Budh (Mercury): trade, growth | **All buying buttons**: Add to cart, Buy now, Place order, success states, veg mark |
  | `tulsi-deep` | `#1B6E42` | Budh + Kuber (North): wealth | Top offer strip, logo text, links, "See all →" |
  | `haldi` | `#F4B400` | Guru (Jupiter): prosperity, auspicious | Offer tags, coupon codes, "Bestseller" badges, footer headings, rating stars. Accent only, never body text on cream |
  | `haldi-deep` | `#8A5A00` | Guru | Gold‑coloured *text* where contrast is needed (e.g. the "शुभ लाभ" mark) |
  | `chandan` | `#FFF4E0` | Chandra (Moon): peace, purity | Main page background, image wells, inputs |
  | `kamal` | `#FDE7E4` | Lakshmi's lotus / Shukra: abundance | Hero gradient, offer panels, soft highlight sections |
  | `mitti` | `#F3E2C3` | Prithvi (earth), South‑West | "About Rasiko" + trust badges block (SW) |
  | `kajal` | `#3E2723` | Warm earth brown (instead of Shani black) | All body text and icons. **Never use pure black `#000`.** |
  | white | `#FFFFFF` | Purity | Cards, header, nav bar |

  - The hero background is a soft "sunrise" radial gradient from light kesari/haldi (`#FFD27A`, `#FFE3B8`) through `kamal` to `chandan`, glowing from the East (right) side like the rising Sun. Category tiles rotate through light haldi, kamal, chandan, mitti and light tulsi (`#EAF7EE`) backgrounds.
  - Cards are white on `chandan`, with 16–22px rounded corners, 1px warm borders (`#F3E3CC`) and soft maroon‑tinted shadows (`rgba(122,31,43,.06)`).
  - Green buttons get a soft green glow shadow. Buttons are pill‑shaped and use the Fredoka font.
  - A visual reference is in `/brand/rasiko-home-preview.png` (homepage) and `/brand/rasiko-vijay-palette.png` (palette). Match that look and feel, and make it even more polished.
- **Rules:** light theme only. **NO dark theme, NO dark mode toggle, NO blue anywhere** (links, buttons, focus rings, charts, Stripe elements — override default blues). Charts use the Vijay Navagraha palette (tulsi, kumkum, kesari, haldi, maroon, tulsi‑deep) on white cards. Colour meanings and placement follow the Vastu rules in 1.1.
- **Font:** "Fredoka" for headings (matches the logo) and "Inter" or "Nunito Sans" for body text, self‑hosted.
- The look should be warm, fresh, appetising and modern, with rounded cards, good product photos, soft shadows and fast, smooth micro‑animations. Mobile first (most customers will be on phones). Also check the WCAG AA contrast.

### 1.1 Vastu Shastra & astrology based design (owner's requirement, follow it on every page)

The owner is religious and wants the site laid out according to **Vastu Shastra**. Treat every screen like a Vastu floor plan: **top = North, right = East, bottom = South, left = West**. Main rule: **light, open and bright at the top/top‑right (North/North‑East); heavy, dense and grounded at the bottom/bottom‑left (South/South‑West); the centre (Brahmasthan) stays open and uncluttered.** Keep normal e‑commerce usability (logo top‑left, cart top‑right, clear checkout); Vastu decides the placement, weight and colour within that.

**Placement (homepage and shared layout):**
| Zone | Meaning | What goes here |
|---|---|---|
| North‑West (top‑left) | Vayavya: movement, selling goods | Logo + categories menu |
| North (top‑centre) | Kuber: wealth | Search bar + thin offer strip (e.g. "Free delivery above ₹499") in green/gold |
| North‑East (top‑right) | Ishanya: sacred, must stay light | A small, elegant auspicious mark ("Shubh Labh" or Om, admin can choose or switch off), plus only light icons (cart, account). No heavy banners or dense content here. |
| West (left) | Varun: gains, profit | Filters/category sidebar on listing pages; Best Sellers row starts on the left on the homepage |
| Centre | Brahmasthan: keep open | Hero slider with generous cream space; no clutter, pop‑ups or heavy text blocks in the middle |
| East (right) | Surya: growth, freshness | "New Arrivals / Fresh Picks" highlight, bright greens |
| South‑West (bottom‑left) | Nairutya: stability, owner | "About Rasiko" / owner's note, trust badges (FSSAI, GST, secure payments) in `mitti` (`#F3E2C3`) |
| South (bottom‑centre) | Yama / Mangal: strength, weight | The footer is the heaviest block, in **`maroon` `#7A1F2B`** with a sunrise‑gradient top border and cream text (this is not a dark theme; the rest of the site stays light) |
| South‑East (bottom‑right) | Agni: fire, food, energy | Floating live help chat bubble in red |

Apply the same logic to the other pages: e.g. on the product page, images go on the left/West and details + "Add to cart" on the right/East. On checkout, the order summary is on the right/East and trust badges sit at the bottom‑left.

**Colours by zone** (from the Vijay Navagraha palette above): North strip in `tulsi-deep` (Kuber/Budh), North‑East kept white/cream with only the small `haldi-deep` "शुभ लाभ" mark, centre on `chandan` with a light `kamal`/`haldi` gradient, East "Fresh Picks" with a light green tint, South‑West in `mitti`, South footer in `maroon`, and South‑East chat bubble in `kumkum`. Avoid black (Shani) and never use blue.

**Small auspicious touches (all switchable in the dashboard → Store settings → "Auspicious elements"):**
- An auspicious mark in the North‑East corner of the header.
- The order success page shows "Shubh Labh 🙏 Thank you for your order" with a subtle kalash/diya illustration (original artwork, SVG).
- Optional festive theme overlays (Diwali diyas, Navratri garba motifs, Makar Sankranti kites, Janmashtami) that the admin can schedule by date. They're toran‑style decorations only; the layout never changes.
- **Launch/muhurat mode:** the admin can set a "go‑live" date and time. Before it, the site shows a "Coming soon: opening on the auspicious day of …" page.

---

## 1.2 Beat the competition (real advantages, not just colours)

Vastu sets the look. These features are what make customers pick Rasiko over quick‑commerce apps and the local shop. Build all of them:
- **Speed promise:** "Rajkot's fastest, 30‑min delivery" badge for nearby areas, with a live ETA on the product page and cart and live order tracking (status timeline + rider details). The admin sets which areas get the 30‑min promise, so it is never a false claim.
- **"Thandu guarantee":** drinks arrive chilled or the customer gets a coupon. One‑tap complaint with a photo from the order page, and the admin approves the coupon.
- **Honest best price:** always show MRP vs Rasiko price and "You save ₹X". There's also a "Price drop" badge and a savings counter in the cart ("You saved ₹86 on this order").
- **Rasiko Coins loyalty:** earn coins on every delivered order (e.g. 2%, set by the admin) and spend them at checkout. Plus a **referral** program (both people get coins), and birthday and festival bonus coins.
- **One‑tap reorder** ("Buy again") and **subscriptions** for daily and weekly items (milk, water cans, cold drinks for shops) with pause and skip.
- **Party & bulk orders:** a special form and quotes for weddings, functions, offices and shops (crates and cases), with bulk price slabs.
- **WhatsApp:** order updates and a "Order on WhatsApp" button (WhatsApp Business API or a click‑to‑chat link as fallback). Order updates also go by email.
- **Gujarati / Hindi / English** language switch for the whole storefront (Django i18n), with Gujarati product names where the admin adds them.
- **Festival campaigns:** a scheduled theme + coupons + a homepage banner for Navratri, Diwali, Uttarayan, Holi and summer (cold drinks peak), all set from the dashboard.
- **Smart suggestions:** "Frequently bought together", "Goes well with" (snacks with drinks later) and combo packs, all driven by the analytics engine.
- **Local SEO:** pages for "cold drinks delivery in Rajkot", "juice home delivery Rajkot" and each area, `LocalBusiness` JSON‑LD, and a guide in the README for the Google Business Profile.
- **Trust:** real verified reviews, FSSAI and GST badges, secure payment badges, and a clear refund policy linked everywhere.
- **Speed of the site itself:** under 2 seconds on a mid‑range phone over 4G (Lighthouse 90+). A slow site loses customers faster than any competitor can.
- **Competitor watch (dashboard):** the admin can note competitor prices for key products, and the insights report flags where Rasiko is costlier or cheaper.

---

## 2. Tech stack

- **Backend:** Python 3.12, Django 5.x, Django REST Framework (for the AJAX/API parts), PostgreSQL 16, Redis, Celery + celery‑beat (emails, reports, stock alerts, reservation expiry), Django Channels (live help chat).
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js (fast, SEO‑friendly, easy to maintain). Chart.js for charts. Leaflet + OpenStreetMap for the delivery location pin (free, no API key).
- **Payments:** Stripe (Payment Intents / Checkout + webhooks) **behind a `PaymentGateway` interface** so another gateway (Razorpay) can be plugged in later without touching order code. Also Cash on Delivery.
- **AI help chat:** Anthropic Claude API (model name read from env, default a fast/cheap model), with a rule‑based FAQ fallback when no API key is set.
- **Infra:** Docker + docker‑compose (web, worker, beat, postgres, redis, nginx), Gunicorn/Uvicorn, WhiteNoise or Nginx for static, local media storage with an optional S3‑compatible backend switch. `.env.example` with every setting documented.
- **Quality:** pytest‑django, factory‑boy, coverage ≥ 80% on orders/payments/stock/delivery/refunds; ruff + black; pre‑commit; bandit + pip‑audit; GitHub Actions CI.

---

## 3. Catalogue — built for ALL food & beverage products and brands

Beverages come first, but the model must handle any food product later without schema changes:
- **Category** (nested tree: e.g. Beverages → Soft Drinks / Juices / Energy Drinks / Water / Tea & Coffee / Milk & Dairy drinks; later Snacks, Sweets, Namkeen, Groceries, Frozen…), with an image, sort order and active flag.
- **Brand** (logo, description, active flag).
- **Product** → **ProductVariant** (size/pack: 250 ml, 500 ml, 1 L, 2 L, pack of 6, 1 kg…). Each variant has: SKU, barcode (optional), MRP, selling price, **cost price** (for profit reports), GST rate + HSN code, weight/volume, **stock quantity**, low‑stock threshold, max quantity per order, active flag.
- Product fields: name, slug, brand, categories, description, images (multiple, drag‑to‑reorder), **veg/non‑veg mark**, ingredients, allergens, nutrition info, shelf life, storage instructions, "best before" note, country of origin, tags, flexible attributes (JSON, e.g. "sugar‑free", "caffeine"), featured/bestseller flags, SEO title/description.
- Storefront: home page (hero slider, categories, brands, best sellers, offers, recently viewed), category and brand pages, search with autocomplete, filters (brand, price, size, veg, rating, in‑stock) and sorting, product page (image gallery, variant picker, stock badge, ratings, related products), cart (mini‑cart drawer), wishlist, checkout, order history, order tracking, invoice download, account/address book.
- **Offers:** coupon codes (percentage/flat, min order, expiry, per‑user limit), plus simple "combo/pack" deals.
- Footer: FSSAI licence number, GSTIN, address, contact, policies (Terms, Privacy, Refund & Cancellation, Shipping/Delivery) — all editable from the dashboard.

---

## 4. Delivery — Rajkot city only, fair and profitable pricing

- **Service area:** only Rajkot city, Gujarat. The admin sets the **store/warehouse location** (lat/lng) and a **service boundary** (max radius in km, default 15 km, plus an optional polygon drawn on a map) and an editable **allowed pincode list** (seed it with Rajkot city pincodes and tell me to verify the list).
- At checkout the customer drops a pin on a Leaflet map (or uses "use my location") and enters their address. If the location or pincode is outside the area, show a friendly "We deliver only within Rajkot city" message and block the order. **Always validate on the server**, never only in the browser.
- **Distance:** straight‑line (Haversine) × road factor (default 1.3, configurable) → estimated road km. Design it so a real routing API (e.g. OSRM) can be swapped in later.
- **Delivery fee = distance slab + rules**, all editable in the dashboard. Seed these starting defaults:

  | Estimated distance | Fee |
  |---|---|
  | 0 – 3 km | ₹25 |
  | 3 – 6 km | ₹35 |
  | 6 – 10 km | ₹45 |
  | 10 – 15 km | ₹60 |

  - Free delivery on orders ≥ ₹499 up to 6 km, and ≥ ₹799 anywhere in the area.
  - Minimum order value ₹99. Small‑order fee ₹15 below ₹199.
  - Optional surcharge toggles: late night (e.g. after 10 pm) and rain/peak (+₹10), shown clearly to the customer.
  - COD limit (default ₹2,000 max order value for COD).
- **Delivery economics (so I earn after delivery costs):** the admin enters the real cost per delivery (rider pay per order + fuel ₹/km + packaging per order). The dashboard shows **delivery income vs delivery cost vs profit per order and per slab**, and warns when a slab or the free‑delivery threshold is making a loss. It also includes a small **"what‑if" calculator** to test new fee settings against last 30 days of orders before saving them.
- **Delivery slots:** "ASAP (30–60 min)" and scheduled time slots, with store opening hours and holidays set by the admin. Show an estimated delivery time.
- Order statuses: Placed → Confirmed → Packed → Out for delivery → Delivered, plus Cancelled / Payment failed / Refunded. Staff can assign a rider name/phone. Optional **delivery OTP** that the customer tells the rider at handover.

---

## 5. Payments — Stripe + Cash on Delivery

- **Important:** new Indian businesses can currently only get a Stripe account **by invite** (Stripe India is invite‑only). So build Stripe fully (as I asked), but through a clean `PaymentGateway` interface, and write a second **Razorpay** implementation (UPI, cards, netbanking, wallets) that I can switch on from settings if Stripe is not approved. Only one gateway active at a time, chosen in the dashboard/env.
- Stripe: Payment Intents/Checkout in **INR**, card + any India‑supported methods, 3‑D Secure, **webhook signature verification**, idempotency keys, handle success/failure/cancel/abandoned payments. **Never trust prices from the browser** — the server recalculates totals, taxes, coupons and delivery fees.
- Stock is **reserved** when online payment starts (e.g. 15 min expiry via Celery) and released on failure/timeout; it is finally deducted on payment success. Use `select_for_update` / atomic transactions so two customers can never buy the last item at the same time.
- **COD:** phone number verification (OTP by SMS if a provider is configured, otherwise by email) before a customer's first COD order, to cut fake orders. The admin can block COD for a user or pincode.
- **GST invoice** PDF for every order (brand logo, GSTIN, HSN, tax breakup), downloadable by the customer and attached to the "delivered" email.
- No card data ever touches or is stored on our server.

---

## 6. Refunds (dashboard)

- On any online‑paid order: **full or partial refund** (by amount or by selected items) from the order page in the dashboard, with a required reason, a confirmation step and permission check (Owner/Manager only).
- Calls the gateway's refund API with an idempotency key, stores refund records, and updates the status from the **webhook** (pending → succeeded/failed). Optionally restock the refunded items.
- COD orders: record a manual refund (UPI/cash/bank) with a reference number.
- Every refund is written to the audit log and **emailed to the admin and the customer**.
- There is a refunds list with filters, and the refund totals feed into the finance reports.

---

## 7. Ratings & reviews

- Only **verified buyers** can rate, and only after the order is delivered: 1–5 stars, a title, a comment and optional photos (validated, resized, EXIF stripped).
- Show the average rating + star breakdown on the product page and cards, and sort by "top rated".
- Admin moderation: approve/hide, reply publicly as "Rasiko Team", and flag abusive content (simple bad‑word filter + rate limits).
- A "Rate your order" email goes out 1 day after delivery.

---

## 8. 24×7 Help Center with live AI chat

- There's a floating chat bubble on every page plus a **Help Center page** (searchable FAQ articles grouped by topic: Orders, Delivery, Payments, Refunds, Account, Products).
- **AI assistant** (Claude API) that answers using **our own site knowledge**: FAQ/articles that the admin manages in the dashboard, policies, delivery rules and fees (read live from settings), store hours, the service area, payment methods and how refunds work. Use retrieval (Postgres full‑text search or pgvector) to pass only relevant articles into the prompt.
- **Tools the assistant can call** (server‑side, permission‑checked):
  - `track_order` — only for the logged‑in owner of the order, or with order number + registered phone/email + OTP. Guest users never see someone else's data.
  - `check_delivery_area(pincode or location)`, `delivery_fee_estimate`, `product_search`, `stock_check`.
- The assistant replies in the **customer's language (English, Gujarati or Hindi)**, is short, friendly and accurate, never invents policies or prices, and says "let me connect you to our team" when unsure.
- **Human handoff:** "Talk to a person" creates a support ticket, emails the admin, and the admin can reply from a **Support Inbox** in the dashboard (live via Channels, and the customer gets an email if they've left).
- It still works without an API key (FAQ matching fallback). Chat has rate limits and a max message length, is protected against prompt injection (tool access is enforced on the server, not by the prompt), and logs conversations for the admin to review. **No payment details are ever asked for in chat.**

---

## 9. Admin dashboard (custom, not just Django admin)

It's a separate, polished dashboard at a non‑obvious URL (`/manage/` style, configurable). It uses the same light brand theme and Vastu logic: the navigation sidebar on the left (West, gains), KPI cards and alerts along the top (North, wealth), a light and uncluttered top‑right (North‑East), and heavy tables and reports lower down (South). **Roles:** Owner, Manager, Staff (Staff can manage orders and stock but not finance, refunds or settings). **2FA (TOTP) required** for Owner/Manager. Every action goes in the audit log.

### 9.1 Products & stock
- Add / edit / duplicate / delete (soft delete + archive) products, variants, categories and brands. Image upload with drag‑and‑drop, reorder and a crop preview.
- **Total quantity is required when adding a product/variant.** The item becomes **Out of stock automatically at 0**, and can come back automatically when restocked.
- A **one‑click "Out of stock / In stock" toggle** on every row of the product list, on the product page, and in a dedicated **Quick Stock** screen (search, then toggle or edit quantity inline via HTMX, no page reload). It's also available from the mobile layout of the dashboard.
- Bulk actions: bulk out‑of‑stock, bulk price update, CSV import/export of products and stock.
- Low‑stock list and alerts. A stock movement history (sale, refund restock, manual adjustment with reason).

### 9.2 Hero image slider manager
- Add / update / remove / reorder slides (drag and drop), each with an image, optional mobile image, heading, sub‑text, button text + link, active dates (start/end) and an active toggle.
- The upload screen **tells the admin the recommended size and ratio** (e.g. "Best: 1920×720 px (8:3) for desktop, 1080×1080 (1:1) for mobile"). There's a **live preview** of how it will look on desktop and mobile.
- **Never force the admin to change the ratio.** If the image has a different ratio, it still fits nicely: show the whole image (`object-fit: contain`) on top of a **blurred, colour‑matched copy of the same image** filling the rest of the slide, with an optional focal‑point picker for cover‑style crops. Generate responsive WebP/AVIF versions with Pillow.
- The slider on the storefront is custom‑built: autoplay with pause on hover, swipe on mobile, dots and arrows, lazy loading, accessible, no layout shift.

### 9.3 Orders
- An order list with filters (status, date, payment type, area) and search, plus an order detail page with a status update, rider assignment, invoice print/download, refund button and customer notes.
- New‑order sound/visual alert in the dashboard and a printable packing slip.

### 9.4 Sales & finance tab (highly detailed)
- **KPIs** (date range picker + compare with the previous period): gross sales, net sales (after discounts/refunds), orders, average order value, **gross profit and margin** (from cost price), delivery income vs cost, GST collected, refunds, cancellation rate, COD vs online split, payment failure rate, new vs returning customers, repeat‑purchase rate.
- **Charts (Chart.js, interactive, brand colours):** revenue & orders over time (day/week/month), profit trend, sales by category, brand and product (top & bottom 10), a heatmap of orders by hour × weekday, sales by area/pincode (a table and a Leaflet map), payment method split, AOV trend, stock value & slow movers, coupon performance, cart/checkout abandonment funnel, and ratings trend.
- A **detailed report table** under the charts: every order line with filters, plus a day‑wise summary, product‑wise and category‑wise summaries, and a GST summary. **Export to CSV/Excel and PDF.**
- An **"Insights & Suggestions" report** below the charts, regenerated daily (Celery) and on demand:
  - **What's going well**, e.g. top growing products, best hours, strong areas.
  - **What can be better**, e.g. products with low margin, high cancellation areas, slow‑moving stock, items often out of stock, low ratings, high delivery losses.
  - **How to improve**: concrete, numbered actions, e.g. "Restock X before Friday evening", "Create a combo of X + Y (often bought together)", "Raise the free‑delivery threshold to ₹549 to cut delivery losses by about ₹N/month", "Run a coupon in area Z", "Stock more of X on weekends".
  - It's built from a **rule‑based analytics engine** (always works), with an optional Claude‑written summary that uses **aggregated numbers only (no customer personal data)**.
- There's also a weekly and monthly summary email to the admin.

### 9.5 Email settings & notifications
- A settings page where the admin enters **SMTP email + app password** (Gmail by default: smtp.gmail.com, 587, TLS; other providers allowed), sender name, and **one or more admin recipient addresses**. The password is **encrypted at rest** (Fernet, key from env), never shown again after saving, with a **"Send test email"** button.
- **Admin emails (each one can be switched on/off):** new order, payment success/failure, order cancelled, product out of stock, low stock, product added / updated / removed (with what changed), price changed, refund issued, new review, new support ticket, daily sales summary, security events (new admin login, failed logins, settings changed).
- **Customer emails:** welcome + email verification, password reset, order placed (with summary), payment received/failed, order confirmed, packed, out for delivery (rider details + OTP), delivered (+ invoice), cancelled, refund initiated/completed, rate your order, back‑in‑stock alert (if subscribed).
- Emails use beautiful branded HTML templates (logo, Vijay Navagraha palette, `chandan` background, `maroon` footer with the sunrise‑gradient border, green buttons, mobile‑friendly) with a plain‑text version. They're sent via Celery with retries, and there's an email log page in the dashboard.

### 9.6 Other dashboard pages
- Customers (orders, lifetime value, block COD), coupons, FAQ/Help Center articles, policies/pages editor, store settings (hours, holidays, delivery rules, payment gateway, GST/FSSAI details), staff users & roles, audit log.

---

## 10. Security (must‑have)

- Follow the **OWASP Top 10**. Use Django's CSRF, XSS‑safe templates, and the ORM only (no raw SQL with user input).
- Hash passwords with **Argon2** and enforce strong password validators. Protect logins against brute force (django‑axes). **Rate limit** login, OTP, checkout, chat, reviews and coupon endpoints.
- 2FA for staff. Session security: Secure/HttpOnly/SameSite cookies, session rotation on login, and auto logout for the admin after inactivity.
- Security headers: **CSP** (django‑csp, with Stripe/Razorpay domains allow‑listed), HSTS, X‑Frame‑Options, Referrer‑Policy, Permissions‑Policy.
- Uploads: allow‑list image types, verify with Pillow, size limits, re‑encode, strip EXIF, random file names, and never serve user uploads as HTML.
- Payments: webhook signature checks, idempotency, amounts calculated on the server, and every order state change done inside transactions.
- Object‑level permission checks on every order/address/review/chat endpoint (no IDOR). Use UUIDs or hashed IDs in public URLs.
- Secrets only in env vars. Encrypt stored SMTP/API credentials. `DEBUG=False` in production, `ALLOWED_HOSTS` set, admin URL configurable.
- The audit log and security emails are covered in section 9. Run nightly DB backups (a script + cron in docker‑compose) and document how to restore.
- Finish with a **security review by a separate subagent**, fix what it finds, and run `bandit`, `pip-audit`, and `python manage.py check --deploy` with zero warnings.

---

## 11. Performance, SEO & compliance

- Fast pages: query optimisation (`select_related`/`prefetch_related`), Redis caching for the catalogue and settings, lazy‑loaded WebP images, and a Lighthouse score of 90+ on mobile.
- SEO: clean slugs, meta tags, Open Graph, `Product` + `Organization` JSON‑LD, sitemap.xml, robots.txt.
- An installable **PWA** (manifest + basic service worker for static assets).
- Cookie/privacy notice, terms, refund policy and delivery policy pages. Show FSSAI and GST details as required for a food business in India.

---

## 12. Seed data & docs

- `python manage.py seed_demo` creates categories, 5–6 beverage brands (use generic/demo brand names, not real trademarks), about 30 products with variants, slider slides, FAQs, delivery settings with the default slabs above, and an Owner account from env vars.
- A `README.md` covering local setup, Docker run, env vars, how to set up Stripe (and Razorpay) keys and webhooks, how to create a Gmail app password, how to set the store location and service area, deployment to a VPS (Nginx + HTTPS with Let's Encrypt), backups and restore.

---

## 13. Build phases (commit + test after each)

1. Project skeleton, Docker, settings split (dev/prod), auth, the brand theme, and base layout with the logo.
2. Catalogue models + admin CRUD + storefront browsing, search and filters.
3. Cart, checkout, delivery area + fee engine, COD, orders, stock reservation.
4. Stripe via `PaymentGateway` + webhooks, Razorpay implementation, invoices, refunds.
5. Email settings, notification engine, all email templates.
6. Dashboard: quick stock, slider manager, orders, customers, coupons.
7. Sales & finance analytics, charts, reports, exports, insights engine, delivery economics.
8. Ratings & reviews, plus the section 1.2 growth features: Rasiko Coins, referral, reorder, subscriptions, bulk/party orders, Thandu guarantee, WhatsApp updates, Gujarati/Hindi/English, festival campaigns, smart suggestions, local SEO and competitor watch.
9. Help Center + AI chat + support inbox.
10. Security hardening, performance, SEO/PWA, full test pass, security review subagent, README.

**Done means:** everything above works end‑to‑end in Docker, the tests pass, `check --deploy` is clean, and you've clicked through a full order flow (browse → cart → checkout with a Rajkot pin → Stripe test payment and COD → admin status updates → emails in the log → refund → review) and shown me screenshots. Also include desktop and mobile screenshots proving the Vastu placement from section 1.1 (header zones, open centre, maroon footer, South‑West trust block, South‑East chat bubble).
