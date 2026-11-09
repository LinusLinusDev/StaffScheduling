"""Review the latest schedule, import a portable pair of files or one plan file, and download them."""

from typing import Annotated, Any, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status

from app.solver.bundle import FileName
from app.solver.review import ScheduleReview

router = APIRouter()


class ScheduleReviewer(Protocol):
    def imported(self, input_json: bytes, result_json: bytes) -> ScheduleReview: ...

    def current(self) -> ScheduleReview | None: ...

    def file(self, name: FileName) -> bytes | None: ...

    def imported_plan(self, content: bytes) -> ScheduleReview: ...

    def plan_file(self) -> tuple[str, bytes] | None: ...


def get_review(request: Request) -> Any:
    return request.app.state.review


Reviewer = Annotated[ScheduleReviewer, Depends(get_review)]

NO_REVIEW = "No schedule to review: generate one or import an input.json/result.json pair. Lost when the API restarts."


@router.get("/review")
def get_current_review(reviewer: Reviewer) -> ScheduleReview:
    if (review := reviewer.current()) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_REVIEW)
    return review


@router.post("/review/import", responses={422: {"description": "Not a valid pair; `problem` names why."}})
def import_review(input: UploadFile, result: UploadFile, reviewer: Reviewer) -> ScheduleReview:
    """Review an uploaded input/result pair; a rejected pair (`InvalidBundle`) leaves the current review unchanged.

    Synchronous, so validating and re-checking the pair runs in FastAPI's worker thread pool.
    """
    return reviewer.imported(input.file.read(), result.file.read())


@router.post("/review/import-plan", responses={422: {"description": "Not a valid plan file; `problem` names why."}})
def import_plan(plan: UploadFile, reviewer: Reviewer) -> ScheduleReview:
    """Review a saved plan file, keeping its version; a rejected file leaves the current review unchanged."""
    return reviewer.imported_plan(plan.file.read())


@router.get("/review/plan")
def download_plan(reviewer: Reviewer) -> Response:
    """The schedule under review as one plan file, named by its month, year and version."""
    if (saved := reviewer.plan_file()) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_REVIEW)
    name, content = saved
    # Browsers take the UTF-8 name; the plain one is a fallback without umlaut.
    plain = name.replace("ä", "ae").encode("ascii", "ignore").decode()
    disposition = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"
    return Response(content, media_type="application/json", headers={"Content-Disposition": disposition})


@router.get("/review/files/{name}")
def download_review_file(name: FileName, reviewer: Reviewer) -> Response:
    if (content := reviewer.file(name)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_REVIEW)
    return Response(
        content,
        media_type="application/json" if name.endswith(".json") else "text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
