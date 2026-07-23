from django.shortcuts import render
from django.utils import timezone

from accounts.emails import send_admin_registration_notice, send_user_decision_notice
from accounts.forms import RegistrationForm
from accounts.models import User
from accounts.tokens import read_decision_token


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.approval_status = User.ApprovalStatus.PENDING
            user.save()
            send_admin_registration_notice(request, user)
            return render(request, "accounts/registration_pending.html")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def admin_decision(request, action, token):
    if action not in ("approve", "reject"):
        return render(request, "accounts/decision_result.html", {"invalid": True})

    user_id = read_decision_token(token, action)
    user = User.objects.filter(pk=user_id).first() if user_id else None

    if user is None:
        return render(request, "accounts/decision_result.html", {"invalid": True})

    if user.approval_status != User.ApprovalStatus.PENDING:
        return render(
            request,
            "accounts/decision_result.html",
            {"already_processed": True, "user": user},
        )

    if request.method == "POST":
        approved = action == "approve"
        user.approval_status = (
            User.ApprovalStatus.APPROVED if approved else User.ApprovalStatus.REJECTED
        )
        user.is_active = approved
        user.approved_at = timezone.now()
        user.save()
        send_user_decision_notice(user, approved)
        return render(
            request,
            "accounts/decision_result.html",
            {"processed": True, "approved": approved, "user": user},
        )

    return render(
        request,
        "accounts/admin_decision_confirm.html",
        {"user": user, "action": action},
    )
