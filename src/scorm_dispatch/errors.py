from __future__ import annotations

from scorm_dispatch.models import FieldError, Problem


class ScormDispatchError(Exception):
    """Any non-2xx answer. Branch on `status`:

    400 malformed request, 401 bad admin key, 403 runtime access refused, 404 not found,
    409 conflict (asset kind change), 422 validation (see `field_errors`), 429 rate limit
    (see `retry_after`), 5xx server side.
    """

    def __init__(self, status: int, problem: Problem, retry_after: int | None = None) -> None:
        self.status = status
        self.problem = problem
        self.retry_after = retry_after
        super().__init__(f"{status} {problem.title}: {problem.detail or ''}".rstrip(": "))

    @property
    def field_errors(self) -> list[FieldError]:
        """Per-field problems of a 422; empty for every other status."""
        return self.problem.errors or []
