from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import DEFAULT_LOG_RETENTION_DAYS
from crud.destination_logs import LOGS_ROOT
from crud.models import Rtmp, Stream


class Command(BaseCommand):
    help = (
        "Удаляет лог-файлы push-процессов (rtmp_logs volume, см. "
        "crud/destination_logs.py) старше срока хранения. Для дестинации, "
        "которая ещё существует в БД, срок — log_retention_days владельца "
        "точки приёма; для файла осиротевшей дестинации (сама точка приёма "
        "или дестинация уже удалены) — общий дефолт, спросить владельца "
        "не у кого. Не трогает .pid — только .log, чтобы не задеть живой "
        "push-процесс, за который отвечает stop.sh."
    )

    def handle(self, *args, **options):
        if not LOGS_ROOT.exists():
            return

        now = timezone.now()
        removed = 0

        for stream_dir in LOGS_ROOT.iterdir():
            if not stream_dir.is_dir():
                continue

            stream = (
                Stream.objects.filter(stream_key=stream_dir.name)
                .select_related("owner")
                .first()
            )

            for log_file in stream_dir.glob("*.log"):
                try:
                    destination_id = int(log_file.stem)
                except ValueError:
                    continue

                retention_days = DEFAULT_LOG_RETENTION_DAYS
                if stream is not None:
                    destination_exists = Rtmp.objects.filter(
                        pk=destination_id, stream=stream
                    ).exists()
                    if destination_exists:
                        retention_days = stream.owner.log_retention_days

                mtime = timezone.datetime.fromtimestamp(
                    log_file.stat().st_mtime, tz=timezone.get_current_timezone()
                )
                if now - mtime > timedelta(days=retention_days):
                    log_file.unlink(missing_ok=True)
                    removed += 1

            try:
                stream_dir.rmdir()
            except OSError:
                pass

        if removed:
            self.stdout.write(f"cleanup_destination_logs: удалено файлов — {removed}")
