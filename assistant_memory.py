from collections import defaultdict
from copy import deepcopy

from shared_logger import get_shared_logger, log_event


logger = get_shared_logger("assistant_memory")

_SESSION_MEMORY = defaultdict(list)

log_event(logger, "module_loaded")


def get_session_messages(session_id: str) -> list[dict]:
    messages = _SESSION_MEMORY.get(session_id, [])
    log_event(
        logger,
        "get_session_messages",
        session_id=session_id,
        message_count=len(messages),
    )
    return deepcopy(messages)


def append_session_message(session_id: str, role: str, content: str):
    log_event(
        logger,
        "append_session_message_start",
        session_id=session_id,
        role=role,
        content_preview=str(content)[:400],
    )

    _SESSION_MEMORY[session_id].append(
        {
            "role": role,
            "content": content,
        }
    )

    log_event(
        logger,
        "append_session_message_end",
        session_id=session_id,
        new_message_count=len(_SESSION_MEMORY[session_id]),
    )


def clear_session_messages(session_id: str):
    old_count = len(_SESSION_MEMORY.get(session_id, []))
    _SESSION_MEMORY[session_id] = []

    log_event(
        logger,
        "clear_session_messages",
        session_id=session_id,
        old_count=old_count,
        new_count=0,
    )


def trim_session_messages(session_id: str, max_messages: int = 20):
    messages = _SESSION_MEMORY.get(session_id, [])
    old_count = len(messages)

    if len(messages) > max_messages:
        _SESSION_MEMORY[session_id] = messages[-max_messages:]
        log_event(
            logger,
            "trim_session_messages_applied",
            session_id=session_id,
            old_count=old_count,
            new_count=len(_SESSION_MEMORY[session_id]),
            max_messages=max_messages,
        )
    else:
        log_event(
            logger,
            "trim_session_messages_skipped",
            session_id=session_id,
            current_count=old_count,
            max_messages=max_messages,
        )