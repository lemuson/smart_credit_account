from http import HTTPStatus

from fastapi.responses import JSONResponse


def problem_response(request, status, code, errors=None):
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://example.local/problems/scoring/{code.lower().replace('_', '-')}",
            "title": HTTPStatus(status).phrase,
            "status": status,
            "code": code,
            "detail": "Scoring request could not be completed.",
            "instance": request.url.path,
            "request_id": str(request.state.request_id),
            "errors": errors or [],
        },
        headers={"X-Request-ID": str(request.state.request_id)},
    )
