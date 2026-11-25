from __future__ import annotations

import re
from dataclasses import dataclass


_TIME_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleIssue:
    code: str
    severity: str
    message: str
    cue_index: int | None = None


def _parse_timestamp(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return total_seconds * 1000 + int(millis)


def _format_timestamp(value_ms: int) -> str:
    value_ms = max(0, int(value_ms))
    hours, remainder = divmod(value_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(content: str) -> list[SubtitleCue]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", normalized.strip())
    cues: list[SubtitleCue] = []

    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        if len(lines) < 2:
            continue

        time_line_index = next(
            (index for index, line in enumerate(lines[:3]) if "-->" in line),
            None,
        )
        if time_line_index is None:
            continue

        match = _TIME_RE.search(lines[time_line_index])
        if not match:
            continue

        text = "\n".join(lines[time_line_index + 1 :]).strip()
        if not text:
            continue

        try:
            index = int(lines[time_line_index - 1].strip()) if time_line_index > 0 else len(cues) + 1
        except ValueError:
            index = len(cues) + 1

        cues.append(
            SubtitleCue(
                index=index,
                start_ms=_parse_timestamp(match.group("start")),
                end_ms=_parse_timestamp(match.group("end")),
                text=text,
            )
        )

    return cues


def to_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for position, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(position),
                    f"{_format_timestamp(cue.start_ms)} --> {_format_timestamp(cue.end_ms)}",
                    cue.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def validate_cues(cues: list[SubtitleCue], max_chars: int = 28) -> list[SubtitleIssue]:
    issues: list[SubtitleIssue] = []
    previous_end = -1

    for cue in cues:
        plain_text = cue.text.replace("\n", "")
        if cue.start_ms >= cue.end_ms:
            issues.append(
                SubtitleIssue(
                    code="CUE_INVALID_DURATION",
                    severity="error",
                    message="Subtitle end time must be greater than its start time.",
                    cue_index=cue.index,
                )
            )
        if cue.start_ms < previous_end:
            issues.append(
                SubtitleIssue(
                    code="CUE_OVERLAP",
                    severity="warning",
                    message="Subtitle timing overlaps the previous cue.",
                    cue_index=cue.index,
                )
            )
        if len(plain_text) > max_chars:
            issues.append(
                SubtitleIssue(
                    code="CUE_TOO_LONG",
                    severity="warning",
                    message=f"Subtitle exceeds {max_chars} characters and may need splitting.",
                    cue_index=cue.index,
                )
            )
        if not plain_text.strip():
            issues.append(
                SubtitleIssue(
                    code="CUE_EMPTY",
                    severity="error",
                    message="Subtitle text is empty.",
                    cue_index=cue.index,
                )
            )
        previous_end = max(previous_end, cue.end_ms)

    return issues
