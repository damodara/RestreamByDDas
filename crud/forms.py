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
