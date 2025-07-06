import time
import functools
from dotenv import load_dotenv
import pyodbc
import os
import traceback
import re


load_dotenv()

CONN_STR = os.getenv("AZURE_SQL_CONNECTION_STRING")
MAX_LOG_LENGTH = 1000


def format_exception(e: Exception) -> str:
    raw_trace = traceback.format_exc()

    # Optional filters: redact file paths, API keys, env vars
    filtered = re.sub(r"(\/[A-Za-z0-9_\-\.]+)+", "[REDACTED_PATH]", raw_trace)
    filtered = re.sub(
        r"(key|token|password)\s*=\s*['\"]?[A-Za-z0-9\-_\+=]+['\"]?",
        r"\1=[REDACTED]",
        filtered,
        flags=re.IGNORECASE,
    )

    return filtered.strip()


def insert_request_stub(
    request_id: str,
    prompt: str,
    content_type: str,
    resolution: str | None = None,
    frame_rate: float | None = None,
):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO GenerationLogs (request_id, prompt, content_type, resolution, frame_rate)
            VALUES (?, ?, ?, ?, ?)
        """,
            request_id,
            prompt,
            content_type,
            resolution,
            frame_rate,
        )
        conn.commit()


def update_request_final_status(request_id: str, status: str, duration_seconds: float):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE GenerationLogs
            SET status = ?, duration_seconds = ?
            WHERE request_id = ?
        """,
            status,
            duration_seconds,
            request_id,
        )
        conn.commit()


def telemetry_step(step_id: int):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request_id = (
                kwargs.get("request_id") or args[0]
            )  # assumes request_id is first or kwarg
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = round(time.perf_counter() - start, 2)
                log_step(request_id, step_id, "completed", duration)
                return result
            except Exception as e:
                error_message = format_exception(e)[:MAX_LOG_LENGTH]
                duration = round(time.perf_counter() - start, 2)
                log_step(request_id, step_id, "failed", duration, error_message)
                raise

        return wrapper

    return decorator


def log_step(request_id, step_id, status, duration, error_message=None):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO GenerationStepLogs (request_id, step_id, status, duration_seconds, error_message)
            VALUES (?, ?, ?, ?, ?)
        """,
            request_id,
            step_id,
            status,
            duration,
            error_message,
        )
        conn.commit()


__all__ = ["telemetry_step", "insert_request_stub", "update_request_final_status"]
