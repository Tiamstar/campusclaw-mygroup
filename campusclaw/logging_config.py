import logging
import os
import re

from flask import has_request_context, request, session


SENSITIVE_FIELDS = re.compile(
    r"(?i)\b(password|secret(?:_key)?|authorization|cookie|csrf(?:_token)?)\b\s*[:=]\s*([^\s,;&]+)"
)


class SensitiveLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for key in ("SECRET_KEY", "SEED_TEACHER_PASSWORD", "SEED_STUDENT_PASSWORD"):
            value = os.environ.get(key)
            if value:
                message = message.replace(value, "[REDACTED]")
        if has_request_context():
            for value in (session.get("auth_token"), session.get("csrf"), request.headers.get("Cookie")):
                if value:
                    message = message.replace(value, "[REDACTED]")
        record.msg = SENSITIVE_FIELDS.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
        record.args = ()
        return True
