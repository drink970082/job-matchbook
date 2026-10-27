"""Legacy name for the neutral model-response error."""
from ats_worker.model_errors import ModelResponseError

ScoreError = ModelResponseError

__all__ = ["ScoreError"]
