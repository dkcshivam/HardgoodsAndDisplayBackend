from rest_framework.permissions import BasePermission

from .models import Role, role_of


class HasRole(BasePermission):
    # What each role may do across the rest of the API is not decided yet;
    # until it is, every signed-in user gets everything but what names a role.
    roles: tuple[Role, ...] = ()

    def has_permission(self, request, view):
        return role_of(request.user) in self.roles


class IsAdmin(HasRole):
    roles = (Role.ADMIN,)
