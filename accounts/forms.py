from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True


class LogRetentionForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["log_retention_days"]
