"""Exceptions shared by the pipeline and the UI."""


class Cancelled(Exception):
    """The user stopped the running job."""


class UserError(Exception):
    """A failure the user can act on. `key` is looked up in i18n for display."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key if not kwargs else f"{key} {kwargs}")
        self.key = key
        self.kwargs = kwargs
