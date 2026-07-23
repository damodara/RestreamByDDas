from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User


class UserAdmin(DjangoUserAdmin):
    list_display = DjangoUserAdmin.list_display + ("approval_status",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Подтверждение регистрации",
            {"fields": ("approval_status", "approved_at", "approved_by")},
        ),
    )
    readonly_fields = ("approved_at", "approved_by")


admin.site.register(User, UserAdmin)
