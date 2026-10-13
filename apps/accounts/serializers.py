from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)

from . import services
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
    role = RoleField(required=False)
    role_label = serializers.SerializerMethodField()
    # Required to create a user. On an edit, one resets it; a blank one, as an
    # untouched form field sends, keeps the old.
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )

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
            "password",
        ]
        read_only_fields = ["last_login", "date_joined"]

    def get_full_name(self, user) -> str:
        return user.get_full_name() or user.username

    def get_role_label(self, user) -> str:
        return role_of(user).label

    def validate(self, attrs):
        password = attrs.get("password")
        if self.instance is None and not password:
            raise serializers.ValidationError({"password": ["This field is required."]})
        if password:
            # Judged against the names it will sit beside after this save.
            named = {
                field: attrs.get(field, getattr(self.instance, field, ""))
                for field in ("username", "first_name", "last_name", "email")
            }
            try:
                validate_password(password, User(**named))
            except DjangoValidationError as error:
                raise serializers.ValidationError({"password": list(error.messages)})
        return attrs

    def create(self, validated_data):
        return services.create_user(validated_data)

    def update(self, user, validated_data):
        return services.update_user(self.context["request"].user, user, validated_data)


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
