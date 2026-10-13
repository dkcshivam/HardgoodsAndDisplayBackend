from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Profile, role_of

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ("role",)


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = (*BaseUserAdmin.list_display, "role")
    list_filter = ("profile__role", *BaseUserAdmin.list_filter)
    list_select_related = ("profile",)

    @admin.display(description="role", ordering="profile__role")
    def role(self, user):
        return role_of(user).label

    def get_inline_instances(self, request, obj=None):
        # Saving the new user already creates its profile; an inline on the
        # add page would try to create a second one. The role is set after.
        return super().get_inline_instances(request, obj) if obj else []
