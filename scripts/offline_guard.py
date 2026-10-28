"""Offline verification guard shared with sequential child interpreters."""

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
INSTALLED = False
VIOLATIONS = []


def install():
    global INSTALLED
    if INSTALLED:
        return
    INSTALLED = True
    audit_path = os.environ.get("RECEIPT_OFFLINE_AUDIT_LOG")

    def reject(reason):
        VIOLATIONS.append(reason)
        if audit_path:
            with open(audit_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "reason": reason}) + "\n")
        raise RuntimeError(reason)

    def audit(event, args):
        if event in {"socket.connect", "socket.sendto", "socket.getaddrinfo"}:
            address = args[1] if event in {"socket.connect", "socket.sendto"} else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "::1", "localhost"}:
                reject("External network access blocked by offline verification")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if path.parent == ROOT and path.name.startswith(".env") and path.name != ".env.example":
                reject("Project secret environment-file access blocked by offline verification")
            if any(part in {"evaluator_private", "held_out", "held-out"} for part in path.parts):
                reject("Private evaluation access blocked by offline verification")

    sys.addaudithook(audit)
    import openai

    def no_client(*args, **kwargs):
        reject("Real SDK client construction blocked by offline verification")

    openai.OpenAI = no_client
    openai.AsyncOpenAI = no_client
