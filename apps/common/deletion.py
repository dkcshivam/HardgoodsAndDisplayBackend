from django.core.files.storage import default_storage
from django.db import transaction
from rest_framework.exceptions import ValidationError


def refuse_if_used(product, orders, templates=()) -> None:
    """
    Orders, their cartons and templates PROTECT a product, so deleting one in
    use would surface as a 500. Say what holds it instead, and the way out.
    """
    holders = []
    if orders:
        holders.append(f"on {_named('order', orders)}")
    if templates:
        holders.append(f"in {_named('template', templates)}")
    if holders:
        raise ValidationError(
            {
                "detail": (
                    f"{product.style_no} is {', and '.join(holders)}. Remove it "
                    "from there first, or mark it inactive instead."
                )
            }
        )


def _named(noun: str, names) -> str:
    # A style in twenty templates would otherwise fill the whole toast.
    names = sorted(set(names))
    shown = ", ".join(names[:5])
    if len(names) > 5:
        shown += f" and {len(names) - 5} more"
    return f"{noun}{'' if len(names) == 1 else 's'} {shown}"


def delete_with_photos(product, photos) -> None:
    """
    Parts and photo rows go with the product by cascade, but the files would
    stay in the bucket. They go once the delete has committed, so a delete
    that fails never loses a photo.
    """
    names = [photo.image.name for photo in photos]

    def remove_files():
        for name in names:
            default_storage.delete(name)

    with transaction.atomic():
        product.delete()
        # A file that will not go must not turn a finished delete into a 500.
        transaction.on_commit(remove_files, robust=True)
