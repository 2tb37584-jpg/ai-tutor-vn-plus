"""Pure deterministic aggregation for persisted tutor sessions."""

from collections.abc import Sequence

from app.models import TutorMessage, TutorSession
from app.schemas.tutor import TutorReplyIntent, TutorSessionSummaryResponse, TutorState


class InvalidTutorSessionState(ValueError):
    """Raised when a persisted session state is not a controlled TutorState."""


def summarize_tutor_session(
    session: TutorSession,
    messages: Sequence[TutorMessage],
) -> TutorSessionSummaryResponse:
    """Summarize persisted reply telemetry without querying or mutating state."""
    try:
        current_state = TutorState(session.current_state)
    except ValueError as error:
        raise InvalidTutorSessionState from error
    user_messages = [message for message in messages if message.role == "user"]

    attempt_value = TutorReplyIntent.ATTEMPT.value
    hint_value = TutorReplyIntent.HINT_REQUEST.value
    attempt_reply_count = sum(
        message.reply_intent == attempt_value for message in user_messages
    )
    hint_request_count = sum(
        message.reply_intent == hint_value for message in user_messages
    )
    unclassified_reply_count = (
        len(user_messages) - attempt_reply_count - hint_request_count
    )

    timed_latencies = [
        message.response_latency_ms
        for message in user_messages
        if message.response_latency_ms is not None
    ]
    average_latency = (
        sum(timed_latencies) / len(timed_latencies) if timed_latencies else None
    )

    return TutorSessionSummaryResponse(
        session_id=session.id,
        primary_skill=session.primary_skill,
        current_state=current_state,
        student_reply_count=len(user_messages),
        attempt_reply_count=attempt_reply_count,
        hint_request_count=hint_request_count,
        unclassified_reply_count=unclassified_reply_count,
        timed_reply_count=len(timed_latencies),
        average_response_latency_ms=average_latency,
    )
