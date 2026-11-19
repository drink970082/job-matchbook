"""Provider response errors raised by the screen backends."""


class ScoreError(RuntimeError):
    """A model provider returned output that cannot be used safely."""


# Keep the legacy exception's runtime name while exposing its neutral ownership.
ModelResponseError = ScoreError
