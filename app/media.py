from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import imageio_ffmpeg


class MediaToolError(RuntimeError):
    pass


def get_ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(arguments: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "FFmpeg failed"
        raise MediaToolError(message)
    return result


def probe_video(video_path: Path) -> dict[str, Any]:
    ffmpeg = get_ffmpeg_path()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    output = result.stderr
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    resolution_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", output)
    duration_seconds = 0.0
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return {
        "duration_seconds": round(duration_seconds, 2),
        "width": int(resolution_match.group(1)) if resolution_match else None,
        "height": int(resolution_match.group(2)) if resolution_match else None,
        "ffmpeg": Path(ffmpeg).name,
    }


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            get_ffmpeg_path(),
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ]
    )
    return audio_path


def render_subtitled_video(video_path: Path, srt_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    escaped_subtitle = str(srt_path).replace("\\", "/").replace(":", "\\:")
    video_filter = (
        f"subtitles='{escaped_subtitle}':"
        "force_style='FontName=Microsoft YaHei,FontSize=20,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,"
        "BorderStyle=1,Outline=2,Shadow=0,MarginV=34'"
    )
    try:
        _run(
            [
                get_ffmpeg_path(),
                "-y",
                "-i",
                str(video_path),
                "-vf",
                video_filter,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            timeout=240,
        )
        return output_path
    except MediaToolError:
        _run(
            [
                get_ffmpeg_path(),
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(srt_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-map",
                "1:0",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "mov_text",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            timeout=240,
        )
        return output_path


def create_demo_video(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            get_ffmpeg_path(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#0C1717:s=1280x720:d=7:r=25",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest",
            "-vf",
            "drawbox=x=72:y=84:w=6:h=170:color=#F36F45:t=fill,"
            "drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            "text='LOCALIZE / STUDIO':x=110:y=96:fontsize=26:fontcolor=#8FD6C7,"
            "drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            "text='A verifier stays in the loop.':x=110:y=150:fontsize=54:fontcolor=white",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=120,
    )
    return output_path
