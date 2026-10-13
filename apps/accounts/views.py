import django_filters
from django.contrib.auth import get_user_model
from django.db.models import F
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import services
from .models import Role
from .permissions import IsAdmin
from .serializers import (
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    RefreshSerializer,
    UserSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer


class LogoutView(APIView):
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            # Expired, already blacklisted or not a token: it opens nothing
            # either way, and signing out should not fail over it.
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class PasswordView(APIView):
    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        services.change_password(request.user, serializer.validated_data["new_password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserFilter(django_filters.FilterSet):
    role = django_filters.ChoiceFilter(choices=Role.choices)

    class Meta:
        model = get_user_model()
        fields = ["role", "is_active"]


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    # No delete: a user who leaves is deactivated, so whatever they recorded
    # still names someone.
    queryset = (
        get_user_model()
        .objects.select_related("profile")
        .annotate(role=F("profile__role"))
        .order_by("username")
    )
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filterset_class = UserFilter
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering_fields = [
        "username",
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
        "last_login",
        "date_joined",
    ]
