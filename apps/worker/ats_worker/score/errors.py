"""ScoreError — raised when fit-scoring backends return unparseable output."""


class ScoreError(RuntimeError):
    """The model returned output we could not parse into a valid score."""
