from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.db import transaction

from maintenance.forms import LoginForm, ChangePasswordForm
from maintenance.services import audit
from maintenance.models import User


class AppLogin(LoginView):
    template_name = "login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class AppLogout(LogoutView):
    pass


@sensitive_post_parameters()
@login_required
def password(request):
    form = ChangePasswordForm(request.user, request.POST or None)
    if request.method == "POST":
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if not user.is_active:
                logout(request)
                return redirect("login")
            form = ChangePasswordForm(user, request.POST)
            if form.is_valid():
                user.set_password(form.cleaned_data["new_password1"])
                user.must_change_password = False
                user.version += 1
                user.save(update_fields=["password", "must_change_password", "version"])
                audit(user, user, "account.password_changed")
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed. Your account is ready.")
                return redirect("dashboard")
    return render(request, "password.html", {"form": form})
