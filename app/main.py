import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.config import get_settings
from app.schemas import (
    ErrorDetail,
    ErrorResponse,
    LinkAnalysisRequest,
    LinkAnalysisResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.llm_service import GeminiLLMService, LLMService
from app.services.website_extractor import WebsiteExtractor
from app.utils.validators import AnalysisError, validate_url

logger = logging.getLogger(__name__)


def configured_key(secret: SecretStr | None) -> str:
    key = secret.get_secret_value().strip() if secret else ""
    return "" if key == "your_api_key_here" else key


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    logger.setLevel(settings.log_level)
    for name in ("analysis_service", "llm_service"):
        logging.getLogger(f"app.services.{name}").setLevel(settings.log_level)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=settings.log_level)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    application.state.analysis_service = None
    gemini_key = configured_key(settings.gemini_api_key)
    if gemini_key:
        with genai.Client(
            api_key=gemini_key,
            vertexai=False,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            ),
        ) as client:
            async with client.aio as async_client:
                application.state.analysis_service = AnalysisService(
                    WebsiteExtractor(settings), GeminiLLMService(async_client, settings)
                )
                yield
        return
    key = configured_key(settings.openai_api_key)
    if not key:
        yield
        return
    async with AsyncOpenAI(
        api_key=key, max_retries=0, timeout=settings.llm_timeout_seconds
    ) as client:
        application.state.analysis_service = AnalysisService(
            WebsiteExtractor(settings), LLMService(client, settings)
        )
        yield


app = FastAPI(
    title="AI-Powered Website Link Analysis API", version="1.0.0", lifespan=lifespan
)


def get_analysis_service(request: Request) -> AnalysisService | None:
    return getattr(request.app.state, "analysis_service", None)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump())


@app.exception_handler(AnalysisError)
async def handle_analysis_error(request: Request, exc: AnalysisError) -> JSONResponse:
    logger.warning("analysis_error code=%s status=%d", exc.code, exc.status)
    return error_response(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_request_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        422, "invalid_request", "Provide a JSON object with a valid string URL."
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unexpected_error type=%s", type(exc).__name__)
    return error_response(500, "internal_error", "The analysis could not be completed.")


@app.get("/", include_in_schema=False)
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


ERRORS = {
    400: "Invalid URL or blocked destination",
    403: "Website denied access",
    404: "Website page was not found",
    413: "Website response exceeded the size limit",
    415: "Unsupported website content",
    422: "Invalid request or unusable website",
    500: "Internal application error",
    502: "Invalid or unavailable upstream response",
    503: "AI provider access unavailable or rate limited",
    504: "Upstream timeout",
}


@app.post(
    "/link-analysis",
    responses={
        status: {"model": ErrorResponse, "description": description}
        for status, description in ERRORS.items()
    },
)
async def link_analysis(
    body: LinkAnalysisRequest,
    service: Annotated[AnalysisService | None, Depends(get_analysis_service)],
) -> LinkAnalysisResponse:
    if service is None:
        validate_url(body.url)
        raise AnalysisError(
            503, "llm_configuration", "AI provider access is unavailable."
        )
    return await service.analyze(body.url)
