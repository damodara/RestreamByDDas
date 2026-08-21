from django import forms

from crud.models import Rtmp, Stream


class StreamForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = ["name"]


class DestinationForm(forms.ModelForm):
    class Meta:
        model = Rtmp
        fields = [
            "socialmedia_name",
            "socialmedia_url",
            "socialmedia_rtmp_link",
            "socialmedia_rtmp_key",
        ]

    def clean_socialmedia_rtmp_key(self):
        key = self.cleaned_data["socialmedia_rtmp_key"]
        conflicts = Rtmp.objects.filter(
            stream=self.instance.stream, socialmedia_rtmp_key=key
        )
        if self.instance.pk:
            conflicts = conflicts.exclude(pk=self.instance.pk)
        if conflicts.exists():
            raise forms.ValidationError(
                "Такой RTMP-ключ уже используется в этой точке приёма."
            )
        return key
