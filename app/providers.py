from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.srt import SubtitleCue


DEMO_TRANSLATIONS = {
    "Every great story begins with a single frame.": "每一段故事，都从一帧开始。",
    "Localization keeps timing, tone, and context intact.": (
        "本地化需要同时保留时间轴、人物语气、上下文和字幕可读性。"
    ),
    "This agent plans, verifies, and retries before delivery.": (
        "这个 Agent 会在交付前规划、验证并重试。"
    ),
}


@dataclass(slots=True)
class ProviderConfig:
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    asr_base_url: str | None
    asr_api_key: str | None
    asr_model: str | None

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL"),
            llm_api_key=os.getenv("LLM_API_KEY"),
            llm_model=os.getenv("LLM_MODEL"),
            asr_base_url=os.getenv("ASR_BASE_URL"),
            asr_api_key=os.getenv("ASR_API_KEY"),
            asr_model=os.getenv("ASR_MODEL"),
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def asr_configured(self) -> bool:
        return bool(self.asr_base_url and self.asr_api_key and self.asr_model)


class DemoTranslationProvider:
    async def translate(
        self,
        cues: list[SubtitleCue],
        source_language: str,
        target_language: str,
    ) -> list[SubtitleCue]:
        translated: list[SubtitleCue] = []
        for cue in cues:
            text = DEMO_TRANSLATIONS.get(
                cue.text,
                f"[{target_language}] {cue.text}",
            )
            translated.append(
                SubtitleCue(
                    index=cue.index,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    text=text,
                )
            )
        return translated


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig) -> None:
        if not config.llm_configured:
            raise ValueError("LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL are required")
        self.config = config

    async def translate(
        self,
        cues: list[SubtitleCue],
        source_language: str,
        target_language: str,
    ) -> list[SubtitleCue]:
        payload = [
            {
                "index": cue.index,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
            }
            for cue in cues
        ]
        prompt = (
            "Translate the subtitle segments as one coherent video. "
            "Preserve meaning, tone, names, numbers, and approximate reading length. "
            "Return JSON only in the form "
            '{"segments":[{"index":1,"text":"..."}]}. '
            f"Source language: {source_language}. Target language: {target_language}.\n"
            f"Segments: {json.dumps(payload, ensure_ascii=False)}"
        )
        url = self.config.llm_base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.config.llm_api_key}"},
                json={
                    "model": self.config.llm_model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a precise audiovisual localization editor.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        parsed = json.loads(content)
        by_index = {
            int(item["index"]): str(item["text"]).strip()
            for item in parsed.get("segments", [])
        }
        return [
            SubtitleCue(
                index=cue.index,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=by_index.get(cue.index, cue.text),
            )
            for cue in cues
        ]

    async def transcribe(self, audio_path: Path) -> str:
        if not self.config.asr_configured:
            raise ValueError(
                "Upload an SRT file or configure ASR_BASE_URL, ASR_API_KEY, and ASR_MODEL"
            )
        url = self.config.asr_base_url.rstrip("/") + "/audio/transcriptions"
        async with httpx.AsyncClient(timeout=180) as client:
            with audio_path.open("rb") as audio_file:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.config.asr_api_key}"},
                    data={
                        "model": self.config.asr_model,
                        "response_format": "srt",
                    },
                    files={"file": (audio_path.name, audio_file, "audio/wav")},
                )
            response.raise_for_status()
        return response.text


def create_translation_provider(config: ProviderConfig, mode: str) -> Any:
    if mode == "demo":
        return DemoTranslationProvider()
    return OpenAICompatibleProvider(config)
