"""
telemetry_utils.py

This module provides telemetry and database logging utilities for the Automated Video Generator project.
It includes decorators and helper functions for logging request and step status, error formatting, and SQL keep-alive.

Features:
    - Telemetry decorator for step-level logging and error tracking
    - Database logging for request and step status
    - Exception formatting and redaction
    - SQL keep-alive background task

These utilities are used throughout the backend to support analytics, debugging, and operational monitoring.
"""
import asyncio
from datetime import datetime
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
    """
    Format and filter an exception traceback for logging.
    Redacts file paths and sensitive keys (e.g., API keys, tokens, passwords).

    Args:
        e (Exception): The exception to format.

    Returns:
        str: The filtered and formatted exception traceback.
    """
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

async def sql_keep_alive_task():
    """
    Periodically pings the SQL database to keep the connection alive.
    Logs a message every 45 minutes.
    """
    while True:
        try:
            with pyodbc.connect(CONN_STR, timeout=5) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                print(f"[KEEP-ALIVE] Pinged SQL at {datetime.now()}", flush=True)
        except Exception as e:
            print(f"[KEEP-ALIVE ERROR] {e}", flush=True)
        await asyncio.sleep(2700)  # 45 mins


def insert_request_stub(
    request_id: str,
    prompt: str,
    content_type: str,
    resolution: str | None = None,
    frame_rate: float | None = None,
):
    """
    Insert a new request record into the GenerationLogs table.

    Args:
        request_id (str): Unique identifier for the request.
        prompt (str): The user prompt for content generation.
        content_type (str): The type of content ('audio' or 'video').
        resolution (str, optional): The video resolution, if applicable.
        frame_rate (float, optional): The video frame rate, if applicable.
    """
    while True:
        try:
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
                break
        except pyodbc.OperationalError as e:
            print(f"Facing issue with connecting to the database: {e}")
        except Exception as e:
            traceback.print_exc()
            raise e


def update_request_final_status(request_id: str, status: str, duration_seconds: float):
    """
    Update the final status and duration of a request in the GenerationLogs table.

    Args:
        request_id (str): Unique identifier for the request.
        status (str): Final status ('completed', 'failed', etc.).
        duration_seconds (float): Total duration of the request in seconds.
    """
    try:
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
    except pyodbc.OperationalError as e:
        print(f"Facing issue with connecting to the database: {e}")
    except Exception as e:
        traceback.print_exc()
        raise e


def telemetry_step(step_id: int):
    """
    Decorator for telemetry logging of step execution.
    Logs completion or failure, duration, and error message if any.

    Args:
        step_id (int): The step identifier for logging.

    Returns:
        Callable: The decorated async function with telemetry logging.
    """
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
    """
    Log the status and duration of a generation step in the GenerationStepLogs table.

    Args:
        request_id (str): Unique identifier for the request.
        step_id (int): The step identifier.
        status (str): Step status ('completed', 'failed', etc.).
        duration (float): Step duration in seconds.
        error_message (str, optional): Error message if the step failed.
    """
    try:
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
    except pyodbc.OperationalError as e:
        print(f"Facing issue with connecting to the database: {e}")
    except Exception as e:
        traceback.print_exc()
        raise e


__all__ = ["telemetry_step", "insert_request_stub", "update_request_final_status", "sql_keep_alive_task"]
