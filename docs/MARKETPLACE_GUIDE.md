# Rasiko marketplace and brand-team operating guide

## Current delivery status

The backend now contains brand Head jurisdiction, seller teams, canonical pincode areas, approval requests, scoped partner screens, product/box/stock editing, seller-funded coupons, multi-brand checkout splitting, rider invitations and APIs, atomic dispatch acceptance, delivery OTP, COD acknowledgements, fee scheduling, translation caching/review and a conservative Razorpay Route transfer adapter.

This is a **local implementation, not production launch approval**. Feature switches default off. Source now includes linked-account onboarding/recovery, provider-confirmed bank settlement, auditable transfer reversals, expiry-batch stock, seller invoice snapshots/PDFs, scoped support cases, delivery resolution, operational alerts and location retention. These flows have local tests against isolated PostgreSQL and mocked providers. Real Route sandbox transactions and physical Android/iPhone behavior still require acceptance testing. Statutory withholding, e-invoicing and international commerce require separate operating decisions and integrations.

Sellers can apply through **Sell with Rasiko** in the storefront footer (`/partners/apply/`). Applications remain inactive and unverified until admin approval, brand-team assignment and territory setup.

## Admin setup

1. Back up PostgreSQL, media and the separate encryption key. Install the usual project dependencies and run release migrations in an isolated database first. New schema: `accounts.0003`, `catalog.0005`, `marketplace.0001` through `0003`. Do not migrate the production database without release authorization.
2. Use the existing Owner login, set up 2FA, and open `/partners/` (also linked as Marketplace in the owner dashboard). Heads and seller owners must also use 2FA; these roles cannot enter the global staff dashboard or its WebSocket feed.
3. Add canonical areas using State, Region, Area and comma-separated pincodes. A pincode belongs to exactly one canonical area. The same brand cannot have two active seller assignments in that area. Pincode boundaries are implemented; map-polygon editing is not implemented.
4. Create a normal account for each intended Head through account registration, then use **Add brand Head** to assign its account, one or more brands and areas across states. **Edit Head and jurisdictions** changes those grants. Never give Heads staff, owner, superuser or global Django permissions.
5. Heads use **Add seller** to create a seller brand team under an assigned brand. The seller receives a password-reset link through configured email. Existing seller accounts can be linked by admin through **Add brand team** after consent. Heads can activate their teams directly; admin business verification is still required before accepting orders.
6. Use **Seller verification and linked account** after checking business information and the approved provider-linked account. Heads cannot alter bank onboarding or platform fees. Linked accounts must be created and approved through Razorpay's provider process; storing an account identifier does not complete onboarding.
7. Assign territories to each team. A seller requests additional territories through **Request territory**; its Head/admin approves or rejects with a reason. Requests add service areas; replacement/removal of an active territory requires an admin-reviewed reassignment workflow and is not exposed as an unsafe delete button.
8. Configure seller products and box variants from **Products and stock**. Stock adjustments count bottles; orders count boxes. Set real stock and prices before launch. The add-only UTF-8 CSV import accepts up to 1,000 new variants / 2 MB, with columns `name,source_language,sku,label,units_per_box,volume_ml,price,mrp,stock_bottles` and optional `cost_price`. Existing/global duplicate SKUs are rejected and the entire import rolls back on any invalid row; edit existing stock separately.
9. Keep **Marketplace**, **Dispatch**, **Translations**, and **Payouts** off until their individual acceptance checks pass. `MARKETPLACE_ROUTE_APPROVED=false` is a second server-side payout gate. No provider account was modified or live money moved during implementation.

## Authority and payment precedence

A Head controls only its brand teams and assigned territories. A seller may have several active brands independently. Once any active team is Head-managed, additional active brands require admin permission in Seller verification and linked account → Allow multiple brands for this Head-managed seller. Existing inactive brand history is retained. A permitted shared seller's other brands, customers, routes and financial entries remain outside a Head's scope. Head dashboards show shared rider availability without exposing unrelated-brand delivery history.

Operational eligibility requires an active verified seller, active team and, when assigned, an active Head with that brand. Territory checks also require the area to remain in the Head's jurisdiction.

COD defaults on. Online defaults off. A Head can turn online on only with a configured Razorpay gateway and a seller marked ready with a linked account. Admin's nullable online/COD overrides mean **inherit**, **force on**, or **force off**. Force on cannot bypass missing provider readiness, seller suspension, existing global COD limits or customer/area COD blocks. Admin can disable all Head campaigns. Removing an override restores the Head/team setting. Admin changes revalidate new checkout/payment attempts; captured payments and order financial snapshots are not rewritten.

Head-managed orders always use standard delivery estimates, including their product page and checkout. Mixed-brand carts split into seller-and-brand fulfillment orders. If one component disallows online, the entire checkout uses COD only when every component permits it; otherwise the buyer must separate incompatible items. Charges and discount allocations reconcile to the parent total to the paise.

## Seller-funded offers and fees

A Head creates a coupon for selected teams, optionally restricted to areas. Select every relevant team for a network-wide offer; newly added teams are not silently charged by an earlier campaign. These coupons apply only to eligible brand lines. One coupon per checkout; no Head/admin coupon stacking. Sellers receive a persistent notice and an email through configured delivery, and their statements record the discount.

Platform commission is zero/off initially. Owner can schedule an enabled percentage or a disabled policy with at least seven days' notice. The latest effective policy applies only to new seller orders. The calculation uses merchandise after discounts and merchandise GST, excluding delivery charges. Gateway charges and statutory withholding are not automatically allocated: agree and configure these before commercial launch. Existing seller orders retain the saved fee version.

## How sellers receive money

### Online

1. Buyer pays the single parent checkout. Rasiko accepts fulfillment only after matching provider capture confirmation.
2. Seller prepares its own brand order; its rider picks up and completes delivery with the buyer's delivery code.
3. A delivered online order records seller proceeds and becomes payout-eligible. Refund reservations/disputes hold submission.
4. With approved Route onboarding and both payout gates enabled, the background worker transfers the seller's eligible amount to its linked account. Loyalty coin value is a platform-funded seller entitlement; Head discounts are seller-funded. If total seller entitlements exceed the captured source payment, automatic transfer is held for funding review.
5. Provider processing determines actual bank settlement timing. **Transferred is not bank-settled.** The worker polls the authoritative transfer and requires settled status plus a recipient settlement identifier before recording bank settlement. Compare provider references with bank statements during the pilot. API mocks do not prove actual bank receipt.

Example with platform fees disabled: merchandise ₹1,000, Head discount ₹100, delivery ₹30 gives customer payment ₹930 and seller entitlement ₹930. This is sales proceeds, not profit; inventory cost, taxes and separately agreed gateway expenses still need accounting.

Route timeouts are treated as uncertain. Recovery searches transfers on the source payment using the saved operation reference. If nothing is found after an uncertain attempt, the system does not blindly create another transfer: an operator investigates. Confirmed refunds after transfer create negative ledger entries and dispute the settlement. Reconciliation creates a proportional reversal operation for each confirmed refund, posting it once after matching provider identity, amount and currency. Uncertain requests are recovered by their saved reference and never blindly submitted again. Keep payouts disabled until sandbox transfer/reversal recovery is accepted.

### Cash on delivery

The rider collects only that fulfillment's COD amount. Completing delivery creates a cash-custody ledger entry. The seller receives the rider's cash and uses **Confirm cash received**; only that seller or admin can acknowledge receipt. Until then the amount stays outstanding. Repeated acknowledgement is idempotent.

No online gateway payout is created for COD. Future platform fees on COD are a seller liability, not a deduction from gateway money that does not exist. Rider wages/fuel are arranged and paid by the seller; payroll is not implemented.

### Refunds

Admin uses existing refund handling. Confirmed refunds are allocated to the specified seller lines or proportionally when no lines are supplied, and posted once in the seller ledger. Pending provider outcomes are not retried blindly. Partial-delivery cancellation and refund decisions require admin review; customer whole-order cancellation is blocked once any seller fulfillment is picked up or delivered. The fulfillment queue exposes cancellation before pickup, with a required reason. It restores only that fulfillment’s stock and reserves its remaining online refund. Picked-up/delivered orders require support resolution. Unpaid online checkout must be cancelled as a whole to release its shared payment hold safely.

## Riders and dispatch

Seller, assigned Head or admin invites a rider email. The one-use invitation is displayed privately once and expires after 48 hours. New riders register in the app; existing accounts sign in with invitation. Each rider belongs to one seller. No public rider enrollment or arbitrary seller selection is available.

When a paid/COD order is marked ready, online eligible idle riders of that seller receive 45-second offers. First valid acceptance wins under database locks and a uniqueness constraint. One active delivery per rider. Two retries follow the initial round; exhausted/unavailable delivery requires seller attention. No customer address is included in push payloads or unaccepted offers.

Riders send availability every 30 seconds. Presence becomes stale after 90 seconds. Location is optional and consented while online; declining location does not fabricate coordinates. Seller/Head dashboards show last seen and stale status. With location consent the app starts a platform position stream (Android foreground location service / iOS background location mode); actual background behavior still needs physical-device verification. Without required permissions, keep the app open; the server will mark lost heartbeats stale. Push delivery and sound also require Firebase/APNs setup, device permissions and user settings.

Delivery codes are encrypted at rest and hashed for verification; the authenticated buyer sees each code on their own order page and receives configured email. They are not returned to riders or Heads. Five wrong attempts block verification pending seller/admin support. OTP reset/reassignment screens remain future work. Suspension/removal requires a reason and retains history; active assignments must first be resolved.

## Languages

Partner interface navigation includes 104+ new Hindi/Gujarati translations, with more existing shared translations reused. Native review and complete form/error translation remain release gates. Rider navigation is supplied in all three languages, with some operational messages still English.

Enable **Google Cloud Translation** in Owner Integrations with a restricted provider key, then enable marketplace translations. Original product text and source language are retained. Translation jobs cache English/Hindi/Gujarati output by source hash; changed text invalidates prior output. Products with ingredients/allergens require seller/admin review before translated text is published. **Review translations** allows corrections. Unavailable translations show original content with a label. No seller must type all three languages.

Nutrition keys, arbitrary structured attributes, category descriptions and search across generated translations are not fully translated by this first implementation. Review brand names, quantities and identifiers before approving generated text. Translation API usage can incur provider charges.

## Release and recovery checklist

- Apply migrations and preview/apply ownership backfill on a restored database; compare historical totals/refunds/stock. The backfill does not create historical ledger payouts or replay old notifications.
- Run PostgreSQL permission, checkout, inventory, payment, coupon and concurrency tests. Review cross-brand exports and customer data boundaries.
- Use synthetic data for browser checks at mobile and desktop sizes; verify all three languages with native speakers.
- Complete native build/signing and real-device notification/background tests before distributing the app. Flutter platform generation, source analysis and multilingual widget tests have been completed locally.
- Verify configured SMTP, Firebase/APNs and Google Translation independently. Failed notifications are not evidence a rider received an offer.
- Verify Route sandbox onboarding, capture, transfer uncertainty, refunds, reversal recovery and actual bank settlement before enabling automatic payouts.
- Provide appropriate seller agreements, grievance/contact handling, retention rules, privacy notices, invoicing/tax review, alerts and off-server backups before launch. These operational/legal documents are not generated automatically.
- Pilot with a small Bailley Rajkot team. If a problem occurs, disable the relevant feature switch; preserve order/ledger data and reconcile pending provider operations. Do not delete or reverse financial migrations casually.

Legacy backfill (after backup and explicit release approval):

```bash
python manage.py backfill_marketplace --owner-email owner@example.com
python manage.py backfill_marketplace --owner-email owner@example.com --apply
```

The first command is read-only. Review open legacy orders before dispatch: migrated order totals remain unchanged, prior payments remain attached to the parent, and no historic payout is invented.

Provider references: [Razorpay Route](https://razorpay.com/route/), [FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send/v1-api), [Apple notification permission](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications).


## Seller onboarding and invoices

Seller owners/admin open **Seller teams → Business and invoice details**. Enter legal name, address, GST state code, registration type, GSTIN when registered, FSSAI details and authorized signatory. Heads cannot access bank/PAN onboarding. Open **Seller payout onboarding**, accept the linked-account terms, and submit provider-approved business category/subcategory and legal/bank details. Sensitive input is encrypted; password-style fields do not echo saved values. Standard Checkout access alone does not establish Route approval. Enable `MARKETPLACE_ROUTE_APPROVED` only after confirming Route access.

Use **Refresh provider status** after provider review. Online readiness requires seller verification, matching account/product identities, activated Route configuration and successful bank configuration. If account/stakeholder/product creation times out, admin finds the existing provider reference and uses **Verify and recover**. **Resume reconciliation** continues saved steps. Bank configuration retry is permitted only after the uncertainty cooldown, using saved encrypted data. Never create replacement provider accounts to bypass an uncertain response.

Issue each fulfillment invoice explicitly from the queue, then download it. Customers have seller invoice links on order details. Issuance snapshots supplier/buyer/items/taxes and a seller financial-year sequence; profile edits do not rewrite issued PDFs. Hindi/Gujarati names use embedded licensed Noto fonts and HarfBuzz shaping. This does not automate IRN, credit notes or statutory withholding. Have your accountant approve registration, rates, HSN, shipping tax and invoice rules before commercial use.

## Expiry batches and delivery exceptions

From a variant choose **Receive expiry-tracked stock**. For existing stock the opening batch must account for every physical bottle, with no unpaid reservation. New receipts increase stock; earliest expiry allocates first. Expired stock is unavailable and expired allocations block pickup preparation. Quarantine removes remaining free stock with a recorded reason. Manual adjustments are blocked for tracked variants. Reconcile damaged/returned goods before restoring them as sellable stock.

The queue includes **Resolve delivery**: cancel before pickup, release an assigned rider before pickup, or reset the buyer code with a reason and one-minute cooldown. Codes remain private to buyers. Releases remain in rider events after reassignment. Customers and scoped operators can open private seller support cases; unrelated teams cannot read them.

## Operational checks and retention

Run `python manage.py marketplace_readiness` for redacted local configuration gates; add `--strict` for a failing exit status when prerequisites are incomplete. It does not enable features or contact providers. Passing does not prove provider/device acceptance. The five-minute monitor tracks unassigned ready orders, stale active riders, disputed settlements, uncertain reversals/onboarding and expiring batches. Failed jobs retain an admin alert until that job succeeds; arguments and exception payloads are not stored. Partners see scoped fulfillment alerts; account alerts are admin-only.

Admin **Privacy and retention settings** configures grievance contacts, policy text, coordinate retention (default seven days) and transient availability retention (default 90 days). Purging removes old coordinates, transient online/offline events and expired credentials; financial, delivery and audit history remains. Publish owner-approved policies before collecting real location data.


Android development APK: generated successfully on 2026-10-24 under the two-worker, 1536 MB profile. See `artifacts/rasiko-rider-debug.apk` and the Rider README. This build uses the configured HTTPS Rasiko origin and foreground polling; it does not deploy the backend, enable marketplace flags or prove phone/background behavior.


### Brand permission and area setup

One brand may have multiple Heads, each with explicit jurisdictions. Independent sellers can have multiple active brand teams. Head-managed sellers default to one active brand; only admin can grant the seller-wide multi-brand exception in **Seller verification and linked account**. A multi-brand independent seller needs this exception before joining a Head. Revoking permission requires deactivating extra brand teams first; historical records and orders are preserved. Head brand/territory access and exclusive active same-brand area assignments still apply.

To add a territory, open **Partner workspace → Add area**. For a Gujarat pilot example enter State `Gujarat`, State code `24`, Region `Rajkot`, Name your actual service area, and comma-separated six-digit pincodes actually served there. Save, then select this area under **Add brand Head** (or edit the Head's jurisdictions). Finally use **Assign territory** for the seller's brand team. Each pincode belongs to one canonical area; the same brand cannot have overlapping active seller assignments. State code is the GST state code, not a pincode or phone code.

## Seller shops and review deployment

A seller application creates a private shop immediately, with one pending brand team for each selected brand and one approval request for every brand/area combination. Select several brands and service areas at registration. No bank details, self-verification or territory assignment are accepted from the seller application. Sign in, complete two-factor authentication, and use **Manage my shop** at `/partners/shops/<seller-id>/`.

The shop workspace includes profile editing, the public visibility switch, setup checklist, catalog/stock/import links, business/invoice details, payout onboarding, support, brands/areas and rider invitations. Orders, delivered income, COD/online totals, fees/refunds/payouts and rider activity remain in the scoped partner dashboard. Product editing stays limited to the seller's active approved brand teams. Sellers request extra brands and areas; admin/authorized Heads retain activation and assignment authority. Independent sellers can have several brands; an active Head-managed team retains the admin-granted multi-brand exception rule. Heads may hold several brands and areas across states; same-brand area exclusivity remains enforced.

Buyer shops live at `/shops/<seller-id>/` only when marketplace is enabled, the seller owner is active, the seller is active/verified, publication is on, and at least one operational brand team has an effective approved service area. Only eligible teams' live products are listed, 24 per page. Shop pages show public name/description and service areas, never bank onboarding, private financial records or Head identities. The shop banner uses standard delivery and address validation, not a Rajkot-wide free/fast promise. Existing sellers also have a workspace without recreating their account or financial history; publication defaults off.

### Rider integration acceptance

The shop uses the same seller affiliation as `/api/v1/rider/`. An invitation from one backend must be registered against that same backend; the production app must use the deployed HTTPS origin. Keep worker/beat running for dispatch and recovery. Local regression checks cover invitation registration, bearer authentication, online heartbeat and JSON offer/delivery lists. They do not certify Firebase/APNs, background notifications, physical delivery OTP/COD operation, real provider payouts or iOS signing. These remain pilot release checks. Do not use the USB loopback APK for a public launch.

### Applying the review branch later

This review includes the previously local marketplace/Rider foundation because GitHub main did not yet contain it. Review account roles, catalog ownership, checkout splitting, financial ledgers/provider recovery, scoped permissions, rider APIs, native source and migrations as well as the new shops. All production rollout remains a separate, approved operation after review.

On a backed-up/restored staging database, install the updated Python 3.12 dependencies and apply accounts 0003, catalog 0005–0006, and marketplace 0001–0006. Preserve the encryption key. Preview the ownership backfill and reconcile before applying it. Existing sellers start with `shop_published=false`. Configure supplier/legal details, Heads, approved brands/areas and API origin, then run `marketplace_readiness`. Exercise two sellers, a shared brand with separate Heads/areas, Head multi-brand permission, mixed checkout, Rider acceptance and COD reconciliation before enabling production. Platform payouts and dispatch are separately gated; no push/merge should automatically enable them.

### Availability and safe switch-off

Turning marketplace off blocks new orders containing seller-linked products, including old carts and bundles, rather than bypassing seller policies through legacy checkout. Unlinked legacy products remain usable. General catalog visibility also requires active verified sellers, active seller owners/teams/brands and valid active Head authority. Plan ownership backfill and marketplace enablement together in a maintenance window: backfilled products are linked inventory and stay unavailable while marketplace is disabled. Captured payments, historical orders and delivery/financial resolution records remain intact.
