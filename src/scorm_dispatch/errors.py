from __future__ import annotations

from typing import Self

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
        message = f"{status} {problem.title}"
        super().__init__(f"{message}: {problem.detail}" if problem.detail else message)

    def __reduce__(self) -> tuple[type[Self], tuple[int, Problem, int | None]]:
        # Exception.__reduce__ would replay the single formatted message as args: unpicklable.
        return (type(self), (self.status, self.problem, self.retry_after))

    @property
    def field_errors(self) -> list[FieldError]:
        """Per-field problems of a 422; empty for every other status."""
        return self.problem.errors or []
