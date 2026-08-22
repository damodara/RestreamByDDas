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
        # socialmedia_rtmp_key зашифровано (EncryptedCharField, не
        # детерминировано) — сравнивать приходится в Python после
        # расшифровки, а не через .filter(socialmedia_rtmp_key=key) в БД
        # (такой фильтр никогда бы не нашёл совпадение).
        key = self.cleaned_data["socialmedia_rtmp_key"]
        siblings = Rtmp.objects.filter(stream=self.instance.stream)
        if self.instance.pk:
            siblings = siblings.exclude(pk=self.instance.pk)
        if any(sibling.socialmedia_rtmp_key == key for sibling in siblings):
            raise forms.ValidationError(
                "Такой RTMP-ключ уже используется в этой точке приёма."
            )
        return key
