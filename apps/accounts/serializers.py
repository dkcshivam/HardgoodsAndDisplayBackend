from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)

from .models import Role, role_of

User = get_user_model()


class RoleField(serializers.ChoiceField):
    def __init__(self, **kwargs):
        super().__init__(choices=Role.choices, **kwargs)

    # Read through role_of, so a superuser always shows as the admin it is.
    def get_attribute(self, user):
        return role_of(user)


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = RoleField()
    role_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "role",
            "role_label",
            "is_active",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["last_login", "date_joined"]

    def get_full_name(self, user) -> str:
        return user.get_full_name() or user.username

    def get_role_label(self, user) -> str:
        return role_of(user).label


class LoginSerializer(TokenObtainPairSerializer):
    # The client needs to know who signed in, and as what, before its first
    # page renders; one round trip instead of a login and then a /me.
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class RefreshSerializer(TokenRefreshSerializer):
    # The stock refresh checks only that the user is still active. Run the
    # same checks as every request, so a changed password ends this session.
    def validate(self, attrs):
        JWTAuthentication().get_user(self.token_class(attrs["refresh"]))
        return super().validate(attrs)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("That is not your current password.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value
