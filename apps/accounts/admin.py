from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm

from .models import Address, User


class UserAddForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "role")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserAddForm
    ordering = ("email",)
    list_display = ("email", "first_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("email", "first_name", "phone")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Profile",
            {"fields": ("first_name", "last_name", "phone", "phone_verified", "birthday", "role", "cod_blocked")},
        ),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),)


admin.site.register(Address)
