from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from apps.core.ratelimit import ratelimit

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup_view, name="signup"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("", views.account_home, name="home"),
    path("profile/", views.profile_edit, name="profile"),
    path("addresses/new/", views.address_edit, name="address_new"),
    path("addresses/<uuid:public_id>/", views.address_edit, name="address_edit"),
    path("addresses/<uuid:public_id>/delete/", views.address_delete, name="address_delete"),
    path("phone/verify/", views.phone_verify, name="phone_verify"),
    path("2fa/setup/", views.twofa_setup, name="2fa_setup"),
    path("2fa/verify/", views.twofa_verify, name="2fa_verify"),
    path(
        "password/reset/",
        ratelimit("pwreset", limit=5, window=600)(
            auth_views.PasswordResetView.as_view(
                template_name="accounts/password_reset.html",
                email_template_name="emails/password_reset.txt",
                html_email_template_name="emails/password_reset.html",
                subject_template_name="emails/password_reset_subject.txt",
                success_url=reverse_lazy("accounts:password_reset_done"),
            )
        ),
        name="password_reset",
    ),
    path(
        "password/reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:login"),
        ),
        name="password_reset_confirm",
    ),
]
