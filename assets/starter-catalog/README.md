# Real-brand starter catalog

32 local-demo product entries (28 active) with downloaded pack photographs, optimized to WebP (maximum 900 px). `catalog.json` records every source image URL and reference page. These are real branded pack photos, not AI-generated images. Source URLs record provenance; they do not grant a redistribution license. Use supplier-approved assets for the live shop.

The user selected popular Indian branded products with demo prices. Prices, stock, taxes, case quantities and jar deposits are examples requiring owner review. No nutritional or expiry claims are imported. Ordinary imports preserve owner edits; the explicit `--configure-demo-boxes` option resets starter box prices/counts/availability only.

The manifest retains the seven Bailley water sizes listed by [Parle Agro](https://www.parleagro.com/brand/1): 250 ml, 500 ml, 1 L, 2 L, 5 L, 10 L and 20 L. Only owner-confirmed 250 ml, 500 ml and 1 L water plus Bailley One 1 L are active. Bailley Soda covers [300 ml, 600 ml and 750 ml](https://www.parleagro.com/brand/9); these three entries deliberately use the official range photograph, with descriptive alt text and a note on the product page. This is coverage of the published Bailley water/soda range, not every regional case configuration or another Parle Agro brand.

Photos were downloaded on 2026-10-09 from BigBasket product assets, Parle Agro (soda range) and ExportersIndia (20 L jar). Packaging editions vary; the shop's supplied packs must be checked before launch.

Install after creating categories on an isolated demo database:

```sh
python manage.py seed_branded_catalog --acknowledge-demo-prices --replace-fictional-demo
```

The optional replacement flag deactivates only the original named fictional seed products, their variants and affected combos. It retains records and order history. The command never runs automatically in migrations, bootstrap or production deployment.


2026-10-09 owner update: only whole boxes are sold. Manifest prices are per box; `demo_bottle_price` is a reference for the explicit provisional configuration (24 up to 600 ml, 12 up to 1 L, 6 above 1 L). Bailley water availability is purple 250/500 ml/1 L and pink Bailley One 1 L. Other water sizes are retained inactive. Bailley One photo: https://bailleyonline.com/product/1-ltr-pink/ (Aditya Agro franchisee storefront). This does not assert photo reuse rights or production prices.
