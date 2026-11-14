import json
import logging
import re
from functools import wraps
from time import perf_counter
from uuid import uuid4

from django.core.exceptions import RequestDataTooBig
from django.db import OperationalError, ProgrammingError
from django.http import JsonResponse
from pydantic import ValidationError

from .errors import APIError
from .models import Actor
from .service import digest

logger = logging.getLogger("tickets.http")
TOKEN = re.compile(r"Bearer ([A-Za-z0-9_-]{32,100})", re.IGNORECASE)
RETRY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,80}")


class RequestContext:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid4()
        started = perf_counter()
        response = self.get_response(request)
        response["X-Request-ID"] = str(request.request_id)
        response["Cache-Control"] = "no-store"
        route = request.resolver_match.url_name if request.resolver_match else "unmatched"
        logger.info("request_id=%s route=%s status=%s duration_ms=%.2f",
                    request.request_id, route, response.status_code,
                    (perf_counter() - started) * 1000)
        return response


def error_response(request, status, code, message, details=None):
    error = {"code": code, "message": message, "request_id": str(request.request_id)}
    if details:
        error["details"] = details
    response = JsonResponse({"error": error}, status=status)
    if status == 401:
        response["WWW-Authenticate"] = "Bearer"
    if status == 503:
        response["Retry-After"] = "1"
    return response


def authenticate(request):
    match = TOKEN.fullmatch(request.headers.get("Authorization", ""))
    actor = Actor.objects.filter(token_digest=digest(match[1]), active=True).first() if match else None
    if actor is None:
        raise APIError(401, "unauthorized", "A valid bearer token is required")
    return actor


def endpoint(**methods):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method.lower() not in methods:
                response = error_response(request, 405, "method_not_allowed", "Method not allowed")
                response["Allow"] = ", ".join(method.upper() for method in methods)
                return response
            try:
                actor = authenticate(request) if methods[request.method.lower()] else None
                return view(request, actor, *args, **kwargs)
            except APIError as exc:
                return error_response(request, exc.status, exc.code, exc.message)
            except ValidationError as exc:
                details = [
                    {"field": ".".join(map(str, item["loc"])) or "body", "type": item["type"]}
                    for item in exc.errors(include_input=False, include_context=False, include_url=False)
                ]
                return error_response(request, 422, "validation_error", "Invalid input", details)
            except RequestDataTooBig:
                return error_response(request, 413, "payload_too_large", "Request exceeds 32 KiB")
            except (OperationalError, ProgrammingError):
                logger.warning("database_unavailable request_id=%s", request.request_id)
                return error_response(request, 503, "service_unavailable", "Database operation unavailable")
            except Exception as exc:
                logger.error("unexpected_error request_id=%s exception_type=%s",
                             request.request_id, type(exc).__name__)
                return error_response(request, 500, "internal_error", "Unexpected server error")

        return wrapped
    return decorate


def unique_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate JSON fields")
    return fields


def reject_constant(value):
    raise ValueError(f"Invalid JSON constant {value}")


def read_body(request, schema):
    if request.content_type != "application/json":
        raise APIError(415, "unsupported_media_type", "Use application/json")
    try:
        data = json.loads(request.body.decode("utf-8"), object_pairs_hook=unique_fields,
                          parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise APIError(400, "invalid_json", "Body must contain valid UTF-8 JSON") from exc
    return schema.model_validate(data)


def read_query(request, schema):
    if any(len(values) != 1 for _, values in request.GET.lists()):
        raise APIError(422, "duplicate_query_parameter", "Each query parameter may appear once")
    return schema.model_validate(request.GET.dict())


def retry_key(request):
    key = request.headers.get("Idempotency-Key")
    if key is not None and not RETRY_KEY.fullmatch(key):
        raise APIError(422, "invalid_retry_key", "Use 1–80 letters, digits, dots, underscores, colons or hyphens")
    return key


def not_found(request, exception):
    return error_response(request, 404, "not_found", "Endpoint not found")


def bad_request(request, exception):
    return error_response(request, 400, "bad_request", "Invalid request")
