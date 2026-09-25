"""
Dump the whole database and put the dump in the private backup bucket. The
server's cron runs it nightly — DEPLOY.md has the line. How long dumps are
kept is the bucket's lifecycle rule, not this command's business.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "pg_dump the database into AWS_BACKUP_BUCKET_NAME."

    def handle(self, *args, **options):
        bucket = settings.AWS_BACKUP_BUCKET_NAME
        if not bucket:
            raise CommandError("Set AWS_BACKUP_BUCKET_NAME first.")

        # Imported here so a setup without boto3 can still list commands.
        import boto3

        db = settings.DATABASES["default"]
        key = f"database/{db['NAME']}_{timezone.localtime():%Y%m%d_%H%M}.dump"

        with tempfile.TemporaryDirectory() as folder:
            dump = Path(folder) / "backup.dump"
            # -Fc: compressed, and restorable table by table with pg_restore.
            subprocess.run(
                [
                    "pg_dump", "-Fc", "--no-owner",
                    "-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"],
                    "-f", str(dump), db["NAME"],
                ],
                env={**os.environ, "PGPASSWORD": db["PASSWORD"]},
                check=True,
            )
            client = boto3.client(
                "s3",
                region_name=settings.S3_MEDIA["region_name"],
                endpoint_url=settings.S3_MEDIA.get("endpoint_url"),
            )
            client.upload_file(str(dump), bucket, key)
            size = dump.stat().st_size

        self.stdout.write(
            self.style.SUCCESS(f"Backed up to s3://{bucket}/{key} ({size:,} bytes).")
        )
