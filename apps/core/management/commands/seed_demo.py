"""python manage.py seed_demo

Creates demo categories, 6 demo brands (made-up names, not real trademarks), ~30 products with variants,
slider slides, FAQs, delivery settings with the default fee slabs, Rajkot pincodes (VERIFY THIS LIST),
store hours, policy pages, coupons and the Owner account from OWNER_EMAIL / OWNER_PASSWORD.
Safe to run more than once.
"""

from datetime import time, timedelta
from decimal import Decimal as D

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Page, StoreSettings
from apps.delivery.models import DeliverySettings, FeeSlab, ServicePincode, StoreHours
from apps.inventory.models import StockMovement
from apps.notifications.models import NotificationSettings
from apps.promotions.models import BulkPriceSlab, Combo, ComboItem, Coupon, HeroSlide
from apps.support.ai import update_faq_vector
from apps.support.models import FaqArticle

CATEGORIES = [
    # name, gujarati, hindi, slug, tile, icon
    ("Soft Drinks", "સોફ્ટ ડ્રિંક્સ", "सॉफ्ट ड्रिंक्स", "soft-drinks", "kamal", "cola"),
    ("Juices", "જ્યુસ", "जूस", "juices", "haldi", "mango"),
    ("Milk & Lassi", "દૂધ અને લસ્સી", "दूध और लस्सी", "milk-lassi", "chandan", "lassi"),
    ("Soda & Masala", "સોડા અને મસાલા", "सोडा और मसाला", "soda-masala", "mitti", "soda"),
    ("Energy", "એનર્જી", "एनर्जी", "energy", "tulsi", "energy"),
    ("Water", "પાણી", "पानी", "water", "white", "water"),
    ("Tea & Coffee", "ચા અને કોફી", "चाय और कॉफ़ी", "tea-coffee", "mitti", "tea"),
]

BRANDS = ["Kathiyawadi Fresh", "Saurashtra Sips", "Gir Dairy", "Rangila Soda Co.", "Tulsi Springs", "Surya Energy"]

# name, gu, brand idx, category slug, illustration, bestseller, new, variants [(label, mrp, price, cost, ml, qty)]
PRODUCTS = [
    (
        "Mango Ras Juice",
        "કેરી રસ જ્યુસ",
        0,
        "juices",
        "mango",
        True,
        False,
        [("1 L", 120, 99, 70, 1000, 60), ("250 ml", 35, 30, 20, 250, 120)],
    ),
    ("Kokum Sherbet", "કોકમ શરબત", 0, "juices", "kokum", False, True, [("750 ml", 95, 85, 55, 750, 40)]),
    ("Orange Burst Juice", "ઓરેન્જ જ્યુસ", 1, "juices", "mango", False, False, [("1 L", 110, 95, 64, 1000, 35)]),
    ("Aam Panna", "આમ પન્ના", 0, "juices", "chaas", False, True, [("500 ml", 60, 55, 34, 500, 30)]),
    ("Guava Delight", "જામફળ જ્યુસ", 1, "juices", "kesar", False, False, [("1 L", 105, 92, 60, 1000, 25)]),
    (
        "Jeera Masala Soda",
        "જીરા મસાલા સોડા",
        3,
        "soda-masala",
        "soda",
        True,
        False,
        [("250 ml", 25, 25, 14, 250, 200), ("Pack of 6", 150, 140, 84, 1500, 30)],
    ),
    ("Kala Khatta Soda", "કાલા ખટ્ટા સોડા", 3, "soda-masala", "kokum", False, False, [("250 ml", 25, 25, 14, 250, 90)]),
    ("Lemon Fizz", "લેમન ફિઝ", 3, "soda-masala", "lemon", True, False, [("330 ml can", 40, 40, 24, 330, 150)]),
    ("Nimbu Shikanji", "નિંબુ શિકંજી", 3, "soda-masala", "chaas", False, True, [("300 ml", 30, 28, 16, 300, 70)]),
    (
        "Cola Classic",
        "કોલા",
        1,
        "soft-drinks",
        "cola",
        True,
        False,
        [("750 ml", 45, 42, 30, 750, 140), ("2 L", 99, 95, 66, 2000, 60), ("Pack of 6 cans", 240, 220, 150, 1800, 20)],
    ),
    ("Orange Fizz", "ઓરેન્જ ફિઝ", 1, "soft-drinks", "mango", False, False, [("750 ml", 45, 42, 30, 750, 80)]),
    ("Clear Lime", "ક્લિયર લાઇમ", 1, "soft-drinks", "water", False, False, [("750 ml", 45, 40, 29, 750, 90)]),
    ("Rose Soda", "રોઝ સોડા", 3, "soft-drinks", "kokum", False, True, [("250 ml", 30, 28, 16, 250, 60)]),
    ("Ginger Ale", "જીંજર એલ", 1, "soft-drinks", "kesar", False, False, [("330 ml can", 50, 45, 30, 330, 45)]),
    ("Kesar Badam Milk", "કેસર બદામ દૂધ", 2, "milk-lassi", "kesar", True, False, [("200 ml", 40, 35, 22, 200, 110)]),
    ("Sweet Lassi", "મીઠી લસ્સી", 2, "milk-lassi", "lassi", True, False, [("200 ml", 25, 25, 15, 200, 100)]),
    ("Masala Chaas", "મસાલા છાશ", 2, "milk-lassi", "chaas", False, True, [("500 ml", 30, 30, 17, 500, 90)]),
    ("Rose Milk", "રોઝ મિલ્ક", 2, "milk-lassi", "kokum", False, False, [("200 ml", 35, 32, 20, 200, 60)]),
    ("Chocolate Shake", "ચોકલેટ શેક", 2, "milk-lassi", "cup", False, False, [("250 ml", 50, 45, 28, 250, 50)]),
    ("Surya Power Energy", "સૂર્ય પાવર", 5, "energy", "energy", True, False, [("250 ml can", 110, 99, 70, 250, 80)]),
    (
        "Tulsi Charge Sugar-free",
        "તુલસી ચાર્જ",
        5,
        "energy",
        "lemon",
        False,
        True,
        [("250 ml can", 120, 110, 78, 250, 40)],
    ),
    ("Glucose Boost", "ગ્લુકોઝ બૂસ્ટ", 5, "energy", "can", False, False, [("500 ml", 60, 55, 36, 500, 50)]),
    (
        "Tulsi Springs Mineral Water",
        "મિનરલ વોટર",
        4,
        "water",
        "water",
        True,
        False,
        [("1 L", 20, 20, 10, 1000, 300), ("20 L can", 90, 80, 45, 20000, 40)],
    ),
    ("Sparkling Water", "સ્પાર્કલિંગ વોટર", 4, "water", "water", False, False, [("500 ml", 40, 35, 22, 500, 60)]),
    ("Coconut Water", "નાળિયેર પાણી", 4, "water", "chaas", False, True, [("200 ml", 45, 40, 27, 200, 50)]),
    ("Masala Chai Cold Brew", "મસાલા ચા", 0, "tea-coffee", "tea", False, True, [("250 ml", 60, 55, 33, 250, 40)]),
    ("Cold Coffee", "કોલ્ડ કોફી", 2, "tea-coffee", "cup", True, False, [("250 ml", 60, 52, 32, 250, 70)]),
    ("Iced Lemon Tea", "આઇસ્ડ લેમન ટી", 1, "tea-coffee", "kesar", False, False, [("500 ml", 50, 45, 28, 500, 55)]),
    ("Thandai", "ઠંડાઈ", 2, "milk-lassi", "lassi", False, False, [("200 ml", 45, 40, 26, 200, 45)]),
    ("Sugarcane Juice", "શેરડીનો રસ", 0, "juices", "chaas", False, True, [("300 ml", 40, 35, 21, 300, 35)]),
]

# Rajkot city pincodes: a STARTING list. Please verify with India Post before going live.
PINCODES = [
    ("360001", "Rajkot HO, Jawahar Road", True),
    ("360002", "Sadar, Race Course", True),
    ("360003", "Bhaktinagar", False),
    ("360004", "Mavdi, Kotecha Chowk", True),
    ("360005", "University Road", True),
    ("360006", "Raiya Road", False),
    ("360007", "Kalawad Road", True),
    ("360020", "Aji Industrial Area", False),
    ("360021", "Kothariya", False),
    ("360022", "Metoda / Lodhika", False),
    ("360023", "Munjka", False),
    ("360024", "Vavdi", False),
    ("360025", "Madhapar", False),
    ("360110", "Gondal Road", False),
]

FAQS = [
    (
        "delivery",
        "Where do you deliver?",
        "We deliver only within Rajkot city. At checkout drop a pin on the map; if "
        "your address is outside our area we'll tell you before you pay.",
        "area location city outside",
    ),
    (
        "delivery",
        "How fast is delivery?",
        "Most orders arrive in 30 to 60 minutes. Nearby areas marked 'Rajkot's "
        "fastest' get a 30-minute promise. You can also pick a scheduled slot.",
        "time eta fast minutes slot",
    ),
    (
        "delivery",
        "How much is the delivery fee?",
        "It depends on distance: ₹25 up to 3 km, ₹35 up to 6 km, ₹45 up "
        "to 10 km and ₹60 up to 15 km. Delivery is free above ₹499 within 6 km and above ₹799 anywhere in our area.",
        "charge fee cost free shipping",
    ),
    (
        "delivery",
        "Is there a minimum order?",
        "Yes, the minimum order is ₹99. Orders below ₹199 have a small order fee of ₹15.",
        "minimum small order",
    ),
    (
        "delivery",
        "What is the Thandu guarantee?",
        "Your drinks arrive chilled or you get a coupon. Open your order "
        "and tap 'Not chilled?' with a photo; our team approves the coupon.",
        "cold chilled warm guarantee",
    ),
    (
        "payments",
        "Which payment methods do you accept?",
        "Cash on Delivery, and UPI, cards, netbanking and wallets "
        "when online payment is on. We never ask for card details in chat.",
        "pay upi card cod cash",
    ),
    (
        "payments",
        "Why do I need to verify my phone for COD?",
        "We verify your mobile number once before your first Cash on Delivery order to prevent fake orders.",
        "otp verify phone cod",
    ),
    (
        "payments",
        "Is paying online safe?",
        "Yes. Payments are handled by the payment gateway; your card details never touch our servers.",
        "secure safe card",
    ),
    (
        "refunds",
        "How do refunds work?",
        "Online payments are refunded to the original payment method, usually in 5 "
        "to 7 working days. Cash orders are refunded by UPI or bank transfer.",
        "refund money back return",
    ),
    (
        "refunds",
        "Can I cancel my order?",
        "Yes, until it is packed. Open the order and tap 'Cancel order'. If you "
        "paid online the refund starts automatically.",
        "cancel",
    ),
    (
        "orders",
        "How do I track my order?",
        "Open 'My account' → your order to see the live status, rider details "
        "and the delivery code. Without an account use 'Track order' in the footer.",
        "track status where rider",
    ),
    (
        "orders",
        "What is the delivery code (OTP)?",
        "It's a 4-digit code on your order page. Tell it to the rider when you receive your order.",
        "otp code rider handover",
    ),
    (
        "orders",
        "Do you take party or wedding orders?",
        "Yes! Use 'Party orders' to request a quote for crates and cases with bulk prices.",
        "bulk wedding party function office shop crates",
    ),
    (
        "account",
        "What are Rasiko Coins?",
        "You earn coins on every delivered order and can use them at checkout. "
        "Invite friends with your referral code and you both get coins.",
        "coins loyalty points referral",
    ),
    (
        "account",
        "How do I change the language?",
        "Use the language menu at the top to switch between English, Gujarati and Hindi.",
        "language gujarati hindi",
    ),
    (
        "products",
        "Are your products genuine?",
        "Yes. We are FSSAI licensed and source directly from brands and authorised distributors.",
        "genuine fake original fssai",
    ),
    (
        "products",
        "Can I subscribe to daily milk or water?",
        "Yes. Open 'Subscriptions' in your account to get daily or weekly deliveries. You can pause or skip any day.",
        "subscription daily weekly milk water can",
    ),
]

PAGES = [
    (
        "about",
        "About Rasiko",
        "A family-run Rajkot business bringing you genuine brands at honest prices, "
        "delivered fresh to your door.\n\nWe started Rasiko to make cold drinks, juices and dairy drinks easy to get "
        "across Rajkot, fast and chilled.",
    ),
    (
        "terms",
        "Terms of use",
        "By using Rasiko you agree to these terms. Please edit this page from the dashboard "
        "with your final legal text.",
    ),
    (
        "privacy",
        "Privacy policy",
        "We collect only the details we need to deliver your order: name, phone, email, "
        "address and location pin. We never sell your data. Payments are processed by our payment gateway; we do not "
        "store card details. Please edit this page from the dashboard with your final legal text.",
    ),
    (
        "refund-policy",
        "Refund & cancellation policy",
        "Orders can be cancelled until they are packed. Online "
        "payments are refunded to the original payment method within 5 to 7 working days. If an item is damaged or "
        "not chilled (Thandu guarantee), report it from your order page within 24 hours.",
    ),
    (
        "delivery-policy",
        "Shipping & delivery policy",
        "We deliver only within Rajkot city. ASAP delivery takes 30 "
        "to 60 minutes. Delivery fees depend on distance and are shown before you pay.",
    ),
]


class Command(BaseCommand):
    help = "Create demo data for Rasiko (safe to re-run)."

    @transaction.atomic
    def handle(self, *args, **opts):
        self._settings()
        cats = self._catalogue()
        self._slides()
        self._faqs()
        self._pages()
        self._promos()
        self._owner()
        self.stdout.write(self.style.SUCCESS(f"Seeded {Product.objects.count()} products in {len(cats)} categories."))
        self.stdout.write(self.style.WARNING("Please verify the Rajkot pincode list in Dashboard → Delivery."))

    def _settings(self):
        StoreSettings.load().save()
        d = DeliverySettings.load()
        d.save()
        if not FeeSlab.objects.exists():
            for lo, hi, fee in [(0, 3, 25), (3, 6, 35), (6, 10, 45), (10, 15, 60)]:
                FeeSlab.objects.create(min_km=D(lo), max_km=D(hi), fee=D(fee))
        for code, area, fast in PINCODES:
            ServicePincode.objects.get_or_create(code=code, defaults={"area": area, "fast_delivery": fast})
        for wd in range(7):
            StoreHours.objects.get_or_create(weekday=wd, defaults={"opens": time(8), "closes": time(23)})
        ns = NotificationSettings.load()
        if not ns.admin_recipients and settings.OWNER_EMAIL:
            ns.admin_recipients = settings.OWNER_EMAIL
        ns.save()

    def _catalogue(self):
        root, _ = Category.objects.get_or_create(
            slug="beverages", defaults={"name": "Beverages", "show_in_menu": False}
        )
        cats = {}
        for i, (name, gu, hi, slug, tile, icon) in enumerate(CATEGORIES):
            cats[slug], _ = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "name_gu": gu,
                    "name_hi": hi,
                    "parent": root,
                    "tile_color": tile,
                    "icon": icon,
                    "sort_order": i,
                },
            )
        brands = [Brand.objects.get_or_create(name=b, defaults={"description": f"{b} (demo brand)"})[0] for b in BRANDS]
        n = 0
        for name, gu, bi, cat, art, best, new, variants in PRODUCTS:
            if Product.objects.filter(name=name).exists():
                continue
            p = Product.objects.create(
                name=name,
                name_gu=gu,
                brand=brands[bi],
                short_description=f"Chilled {name.lower()}, delivered fast.",
                description=f"{name} from {brands[bi].name}. Serve chilled. Best enjoyed on a hot Rajkot afternoon.",
                ingredients="Water, sugar, natural flavours" if "Water" not in name else "Purified water, minerals",
                shelf_life="6 months" if "Milk" not in cat else "3 days (keep refrigerated)",
                storage_instructions="Store in a cool, dry place. Refrigerate after opening.",
                nutrition={"Energy": "45 kcal / 100 ml", "Sugar": "10 g / 100 ml"},
                illustration=art,
                is_bestseller=best,
                is_new=new,
                is_featured=best,
                tags=[cat.replace("-", " ")],
                attributes={"sugar_free": "Sugar-free" in name},
            )
            p.categories.add(cats[cat])
            for j, (label, mrp, price, cost, ml, qty) in enumerate(variants):
                n += 1
                gst = D("5") if cat in ("milk-lassi",) else (D("18") if cat in ("water", "tea-coffee") else D("12"))
                if cat in ("soft-drinks", "energy", "soda-masala") and "Nimbu" not in name:
                    gst = D("28") if cat in ("soft-drinks", "energy") else D("12")
                v = ProductVariant.objects.create(
                    product=p,
                    label=label,
                    sku=f"RSK-{p.pk:03d}-{j + 1}",
                    mrp=D(mrp),
                    price=D(price),
                    cost_price=D(cost),
                    gst_rate=gst,
                    hsn_code="0401" if cat == "milk-lassi" else "2202",
                    volume_ml=ml,
                    stock_qty=qty,
                    sort_order=j,
                )
                StockMovement.objects.create(
                    variant=v, delta=qty, balance_after=qty, reason=StockMovement.Reason.INITIAL
                )
        soda = ProductVariant.objects.filter(product__name="Jeera Masala Soda", label="250 ml").first()
        if soda and not soda.bulk_slabs.exists():
            BulkPriceSlab.objects.create(variant=soda, min_qty=24, unit_price=D("22"))
            BulkPriceSlab.objects.create(variant=soda, min_qty=96, unit_price=D("20"))
        return cats

    def _slides(self):
        if HeroSlide.objects.exists():
            return
        HeroSlide.objects.create(
            heading="Thandu thandu,",
            heading_accent="tamare ghare!",
            subtext="Chilled beverages delivered across Rajkot in under an hour.",
            badge="Rajkot's fastest · 30 min delivery",
            button_text="Shop now",
            button_link="/search/",
            art="mango,cola,lemon",
            theme="sunrise",
            sort_order=0,
        )
        HeroSlide.objects.create(
            heading="Chilled on arrival,",
            heading_accent="or a coupon on us.",
            subtext="Every drink leaves our cold room minutes before it reaches your door.",
            badge="Thandu guarantee",
            button_text="Order now",
            button_link="/search/",
            art="water,lassi,lemon",
            theme="green",
            sort_order=1,
        )
        HeroSlide.objects.create(
            heading="Crates for every",
            heading_accent="function & prasang.",
            subtext="Weddings, offices and shops get bulk prices and on-time delivery.",
            badge="Party & bulk orders",
            button_text="Get a quote",
            button_link="/orders/party/",
            art="cola,soda,mango",
            theme="pink",
            sort_order=2,
        )

    def _faqs(self):
        for i, (topic, q, a, kw) in enumerate(FAQS):
            art, _ = FaqArticle.objects.get_or_create(
                question=q, defaults={"topic": topic, "answer": a, "keywords": kw, "sort_order": i}
            )
            update_faq_vector(art)

    def _pages(self):
        for i, (slug, title, body) in enumerate(PAGES):
            Page.objects.get_or_create(slug=slug, defaults={"title": title, "body": body, "sort_order": i})

    def _promos(self):
        Coupon.objects.get_or_create(
            code="SHUBH50",
            defaults={
                "description": "Festive offer: flat ₹50 off on orders above ₹599",
                "kind": Coupon.Kind.FLAT,
                "value": D("50"),
                "min_order": D("599"),
                "per_user_limit": 3,
                "show_on_home": True,
                "expires_at": timezone.now() + timedelta(days=60),
            },
        )
        Coupon.objects.get_or_create(
            code="SWAAD10",
            defaults={
                "description": "10% off your first order (up to ₹75)",
                "kind": Coupon.Kind.PERCENT,
                "value": D("10"),
                "max_discount": D("75"),
                "min_order": D("199"),
                "first_order_only": True,
            },
        )
        if not Combo.objects.exists():
            combo = Combo.objects.create(
                name="Party pack", description="6 × Cola Classic 750 ml + 6 × Jeera Soda", price=D("370")
            )
            for pname, label, qty in [("Cola Classic", "750 ml", 6), ("Jeera Masala Soda", "250 ml", 6)]:
                v = ProductVariant.objects.filter(product__name=pname, label=label).first()
                if v:
                    ComboItem.objects.create(combo=combo, variant=v, qty=qty)

    def _owner(self):
        email, pw = settings.OWNER_EMAIL, settings.OWNER_PASSWORD
        if email and pw and not User.objects.filter(email=email.lower()).exists():
            User.objects.create_superuser(email=email, password=pw, first_name="Owner")
            self.stdout.write(self.style.SUCCESS(f"Owner account created: {email}"))
