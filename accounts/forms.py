from django import forms
from django.contrib.auth.forms import UsernameField, UserCreationForm

from accounts.models import User


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True


class AccountIdentityForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email"]
        field_classes = {"username": UsernameField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "log_retention_days",
            "notify_on_push_error",
            "auto_end_broadcast_on_drop",
        ]
