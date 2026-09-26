def local_storage(folder) -> dict:
    """STORAGES that keep uploads in a folder, so no test ever writes to S3."""
    return {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            # The prefix every image carries in the bucket, so URLs look alike.
            "OPTIONS": {"location": str(folder), "base_url": "/media/"},
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
