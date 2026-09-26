"""
Copy uploaded images from a local folder into the configured storage — once,
for a machine that kept its images on disk before they moved to S3. The
database keeps each image's path, so every file lands at the same path it had
on disk. Safe to re-run: files already there are skipped.
"""

from pathlib import Path

from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copy every file under a media folder into the default storage (S3)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="The old media/ folder to copy from."
        )

    def handle(self, *args, source, **options):
        root = Path(source).resolve()
        if not root.is_dir():
            raise CommandError(f"There is no folder at {root}.")
        if (
            isinstance(default_storage, FileSystemStorage)
            and Path(default_storage.location).resolve() == root
        ):
            raise CommandError(
                "Storage is this same folder — set AWS_STORAGE_BUCKET_NAME first."
            )

        copied = skipped = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            name = path.relative_to(root).as_posix()
            if default_storage.exists(name):
                skipped += 1
                continue

            with path.open("rb") as handle:
                saved = default_storage.save(name, File(handle))
            # A renamed file would leave its database row pointing nowhere.
            if saved != name:
                raise CommandError(f"{name} was stored as {saved}.")
            copied += 1
            self.stdout.write(f"  {name}")

        self.stdout.write(
            self.style.SUCCESS(f"Copied {copied}, already there {skipped}.")
        )
