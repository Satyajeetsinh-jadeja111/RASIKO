"""Media storage: local disk by default, S3-compatible when the Owner enables the 's3' integration."""

from django.core.files.storage import FileSystemStorage
from django.utils.functional import LazyObject


class SwitchableMediaStorage(LazyObject):
    def _setup(self):
        from .integrations import get_config

        try:
            cfg = get_config("s3")
        except Exception:  # noqa: BLE001 - database not ready (migrations, first boot)
            cfg = None
        if cfg:
            from storages.backends.s3 import S3Storage

            self._wrapped = S3Storage(
                bucket_name=cfg["bucket"],
                endpoint_url=cfg.get("endpoint_url") or None,
                region_name=cfg.get("region") or None,
                access_key=cfg["access_key"],
                secret_key=cfg["secret_key"],
                custom_domain=cfg.get("custom_domain") or None,
                file_overwrite=False,
                default_acl=None,
                querystring_auth=False,
            )
        else:
            self._wrapped = FileSystemStorage()


def test_connection(config):
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=config.get("endpoint_url") or None,
        region_name=config.get("region") or None,
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
    )
    client.head_bucket(Bucket=config["bucket"])
    return True, "Bucket reachable."


def reset_storage():
    """Pick up a changed S3 setting in this process. Other worker processes switch on their next restart."""
    from django.core.files.storage import storages
    from django.utils.functional import empty

    backend = storages["default"]
    if isinstance(backend, SwitchableMediaStorage):
        backend._wrapped = empty
