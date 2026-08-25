from urllib.parse import parse_qs, urlparse

from django import forms

from crud.models import Rtmp, Stream


class StreamForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = ["name"]


class StreamChatForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = ["youtube_chat_video_id"]
        labels = {"youtube_chat_video_id": "Ссылка на трансляцию или её Video ID"}

    def clean_youtube_chat_video_id(self):
        # Пользователю проще вставить ссылку из адресной строки/студии, чем
        # искать в ней голый video ID — принимаем оба варианта.
        value = self.cleaned_data["youtube_chat_video_id"].strip()
        if not value:
            return value
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if host.endswith("youtube.com"):
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            if video_id:
                return video_id
        if host.endswith("youtu.be"):
            video_id = parsed.path.lstrip("/")
            if video_id:
                return video_id
        return value


class DestinationForm(forms.ModelForm):
    # Уникальность RTMP-ключа в рамках Stream проверяется в Rtmp.clean()
    # (модель), не здесь — так проверка срабатывает и для этой формы,
    # и для Django admin, у которого своя автосгенерированная ModelForm.
    class Meta:
        model = Rtmp
        fields = [
            "socialmedia_name",
            "socialmedia_url",
            "socialmedia_rtmp_link",
            "socialmedia_rtmp_key",
        ]
