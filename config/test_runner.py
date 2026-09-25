"""
Tests keep uploads in a throwaway local folder whatever .env says, so running
them where S3 is configured — the server included — can never put test images
in the real, public bucket, or a test dump in the backup one.
"""

import shutil
import tempfile

from django.test import override_settings
from django.test.runner import DiscoverRunner


class LocalStorageRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self.media_root = tempfile.mkdtemp()
        self.local_storage = override_settings(
            USE_S3=False,
            MEDIA_ROOT=self.media_root,
            AWS_BACKUP_BUCKET_NAME="",
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            },
        )
        self.local_storage.enable()

    def teardown_test_environment(self, **kwargs):
        self.local_storage.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
