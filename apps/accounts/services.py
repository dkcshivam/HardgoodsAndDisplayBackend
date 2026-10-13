def change_password(user, password: str) -> None:
    # The tokens carry a hash of the old password (CHECK_REVOKE_TOKEN), so
    # every session this user has, this one included, ends here.
    user.set_password(password)
    user.save(update_fields=["password"])
