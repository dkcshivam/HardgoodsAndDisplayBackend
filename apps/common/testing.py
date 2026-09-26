def local_storage(folder) -> dict:
    """
    STORAGES that keep uploads in a folder, so no test ever writes to S3, and
    serve static files unhashed: tests never run collectstatic, so the
    manifest WhiteNoise reads would not exist for a page that renders.
    """
    return {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            # The prefix every image carries in the bucket, so URLs look alike.
            "OPTIONS": {"location": str(folder), "base_url": "/media/"},
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
