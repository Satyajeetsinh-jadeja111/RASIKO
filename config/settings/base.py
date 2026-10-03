"""Base settings shared by every environment.

Only bootstrap secrets live in the environment (.env). Every third-party API key
(Stripe, Razorpay, WhatsApp, Claude, SMS, SMTP, S3) is entered by the Owner in
Dashboard -> Settings -> Integrations and stored encrypted in the database.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")

# Fernet key that encrypts integration secrets and SMTP passwords at rest.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

# The dashboard lives at a non-obvious, configurable URL.
ADMIN_URL = env("ADMIN_URL", default="manage/").strip("/") + "/"
DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL", default="django-admin-x/").strip("/") + "/"

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "django.contrib.postgres",
    # third party
    "rest_framework",
    "django_celery_beat",
    "channels",
    "axes",
    "csp",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "django_htmx",
    # local
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.inventory",
    "apps.cart",
    "apps.delivery",
    "apps.orders",
    "apps.payments",
    "apps.promotions",
    "apps.reviews",
    "apps.notifications",
    "apps.support",
    "apps.analytics",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.PermissionsPolicyMiddleware",
    "apps.core.middleware.LaunchModeMiddleware",
    "apps.dashboard.middleware.StaffSessionMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.core.context_processors.store",
                "apps.cart.context_processors.cart",
                "apps.dashboard.context_processors.dashboard",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://rasiko:rasiko@localhost:5432/rasiko"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient", "IGNORE_EXCEPTIONS": True},
        "KEY_PREFIX": "rasiko",
    }
}
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}},
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.EmailBackend",
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "storefront:home"
LOGOUT_REDIRECT_URL = "storefront:home"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Brute-force protection
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_FORM_FIELD = "username"

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("gu", "ગુજરાતી"), ("hi", "हिन्दी")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "apps.core.storage.SwitchableMediaStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "user": "240/min", "chat": "20/min"},
}

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
# Installed into the database scheduler on start; times can be changed later in Django admin -> Periodic tasks.
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "expire-stock-reservations": {"task": "apps.inventory.tasks.expire_reservations", "schedule": 60.0},
    "run-subscriptions": {"task": "apps.orders.tasks.run_subscriptions", "schedule": crontab(hour=6, minute=0)},
    "daily-insights": {"task": "apps.analytics.tasks.daily_insights", "schedule": crontab(hour=5, minute=30)},
    "daily-summary": {"task": "apps.analytics.tasks.daily_summary", "schedule": crontab(hour=23, minute=30)},
    "weekly-summary": {
        "task": "apps.analytics.tasks.weekly_summary",
        "schedule": crontab(hour=8, minute=0, day_of_week="mon"),
    },
    "birthday-coins": {"task": "apps.promotions.tasks.birthday_coins", "schedule": crontab(hour=7, minute=0)},
}

# Email: the real SMTP settings come from the dashboard (notifications.EmailSettings).
EMAIL_BACKEND = "apps.notifications.backends.DashboardSMTPBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Rasiko <no-reply@localhost>")

# Sessions & cookies
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
STAFF_IDLE_TIMEOUT_SECONDS = env.int("STAFF_IDLE_TIMEOUT_SECONDS", default=30 * 60)
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Content Security Policy (django-csp 4). Payment domains allow-listed.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": [
            "'self'",
            "https://js.stripe.com",
            "https://checkout.razorpay.com",
        ],
        # Inline style attributes are used for per-item colours (tiles, slides); no inline scripts are allowed.
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "blob:", "https://*.tile.openstreetmap.org", "https://*.razorpay.com"],
        "font-src": ["'self'"],
        "connect-src": [
            "'self'",
            "https://api.stripe.com",
            "https://*.razorpay.com",
            "https://nominatim.openstreetmap.org",
        ],
        "frame-src": ["https://js.stripe.com", "https://hooks.stripe.com", "https://api.razorpay.com"],
        "form-action": ["'self'", "https://api.razorpay.com"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}

# Business defaults (all editable in the dashboard once seeded)
OWNER_EMAIL = env("OWNER_EMAIL", default="")
OWNER_PASSWORD = env("OWNER_PASSWORD", default="")
