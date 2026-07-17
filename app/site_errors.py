class BlockedError(RuntimeError):
    """The remote site denied or restricted access; stop the batch."""


class PageChangedError(RuntimeError):
    """The page no longer satisfies the adapter's required contract."""


class NetworkError(RuntimeError):
    """A bounded, retryable navigation or connection failure."""


class SiteProtectionChallenge(RuntimeError):
    """A site-protection challenge that must never be automated around."""
