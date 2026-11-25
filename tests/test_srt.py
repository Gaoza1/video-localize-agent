from app.srt import SubtitleCue, parse_srt, to_srt, validate_cues


SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
Every great story begins with a single frame.

2
00:00:02,100 --> 00:00:04,500
Localization keeps timing, tone, and context intact.
"""


def test_parse_srt_preserves_timing_and_text() -> None:
    cues = parse_srt(SAMPLE_SRT)

    assert len(cues) == 2
    assert cues[0].start_ms == 0
    assert cues[0].end_ms == 2000
    assert cues[1].text == "Localization keeps timing, tone, and context intact."


def test_to_srt_round_trips_timing() -> None:
    rendered = to_srt(
        [
            SubtitleCue(1, 150, 2250, "第一帧"),
            SubtitleCue(2, 2400, 4800, "第二帧"),
        ]
    )

    assert "00:00:00,150 --> 00:00:02,250" in rendered
    assert parse_srt(rendered)[1].text == "第二帧"


def test_validate_cues_reports_overlong_text() -> None:
    cues = [SubtitleCue(1, 0, 2000, "这是一条明显超过推荐长度的字幕，需要拆分以便观众阅读")]

    issues = validate_cues(cues, max_chars=20)

    assert len(issues) == 1
    assert issues[0].code == "CUE_TOO_LONG"
    assert issues[0].severity == "warning"


def test_validate_cues_reports_overlapping_timing() -> None:
    cues = [
        SubtitleCue(1, 0, 2500, "第一段"),
        SubtitleCue(2, 2000, 4000, "第二段"),
    ]

    issues = validate_cues(cues, max_chars=40)

    assert any(issue.code == "CUE_OVERLAP" for issue in issues)
