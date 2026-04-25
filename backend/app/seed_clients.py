from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageEnhance, ImageFilter

from .config import Settings


class SeedanceKeyRotator:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self._idx = 0

    def next(self) -> str:
        if not self._keys:
            return ""
        key = self._keys[self._idx % len(self._keys)]
        self._idx += 1
        return key


class SeedreamClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def polish_keyframe(self, image_path: Path, prompt: str, out_path: Path) -> Path:
        if self.settings.use_mock_mode or not self.settings.seedream_api_key:
            await asyncio.to_thread(_mock_polish_image, image_path, out_path)
            return out_path

        # NOTE: ModelArk surface changes by account/region.
        # This payload shape is intentionally conservative and override-friendly.
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            with image_path.open("rb") as img_fp:
                files = {"file": (image_path.name, img_fp, "image/jpeg")}
                upload = await client.post(
                    f"{self.settings.seedream_base_url}/files",
                    headers={"Authorization": f"Bearer {self.settings.seedream_api_key}"},
                    files=files,
                )
                upload.raise_for_status()
                upload_id = upload.json().get("id")

            job = await client.post(
                f"{self.settings.seedream_base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.settings.seedream_api_key}"},
                json={
                    "model": self.settings.seedream_model,
                    "prompt": prompt,
                    "image_ids": [upload_id],
                    "size": "16:9",
                    "n": 1,
                },
            )
            job.raise_for_status()
            result_url = job.json().get("data", [{}])[0].get("url")

            if not result_url:
                raise RuntimeError("Seedream returned no image URL.")
            data = await client.get(result_url)
            data.raise_for_status()
            out_path.write_bytes(data.content)
            return out_path


class SeedanceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._rotator = SeedanceKeyRotator(settings.seedance_key_pool())

    async def image_to_video(self, image_path: Path, motion_prompt: str) -> str:
        if self.settings.use_mock_mode:
            return f"mock://clip/{image_path.stem}"

        key = self._rotator.next()
        if not key:
            raise RuntimeError("No Seedance API key configured.")

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            with image_path.open("rb") as img_fp:
                files = {"file": (image_path.name, img_fp, "image/jpeg")}
                upload = await client.post(
                    f"{self.settings.seedance_base_url}/files",
                    headers={"Authorization": f"Bearer {key}"},
                    files=files,
                )
                upload.raise_for_status()
                image_id = upload.json().get("id")

            created = await client.post(
                f"{self.settings.seedance_base_url}/video/generations",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": self.settings.seedance_model,
                    "image_id": image_id,
                    "prompt": motion_prompt,
                    "duration": 5,
                    "resolution": "1080p",
                    "aspect_ratio": "16:9",
                },
            )
            created.raise_for_status()
            task_id = created.json().get("id") or created.json().get("job_id")
            if not task_id:
                raise RuntimeError("Seedance did not return a task id.")

            deadline = asyncio.get_running_loop().time() + self.settings.poll_timeout_s
            while True:
                status = await client.get(
                    f"{self.settings.seedance_base_url}/video/generations/{task_id}",
                    headers={"Authorization": f"Bearer {key}"},
                )
                status.raise_for_status()
                payload: dict[str, Any] = status.json()
                state = payload.get("status", "").lower()
                if state in {"completed", "succeeded", "success"}:
                    return payload.get("video_url") or payload.get("output", {}).get("video_url")
                if state in {"failed", "error", "canceled", "cancelled"}:
                    raise RuntimeError(f"Seedance generation failed: {payload}")
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError(f"Seedance generation timed out for task {task_id}")
                await asyncio.sleep(self.settings.poll_interval_s)


class SeedSpeechClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize(self, text: str, out_path: Path) -> Path:
        if self.settings.use_mock_mode or not self.settings.seed_speech_api_key:
            # A silent placeholder file still allows front-end and video merge flow tests.
            out_path.write_bytes(b"")
            return out_path

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            response = await client.post(
                f"{self.settings.seed_speech_base_url}/api/v1/tts",
                headers={"Authorization": f"Bearer {self.settings.seed_speech_api_key}"},
                json={
                    "text": text,
                    "voice_type": self.settings.seed_speech_voice,
                    "encoding": "mp3",
                },
            )
            response.raise_for_status()
            out_path.write_bytes(response.content)
            return out_path


def _mock_polish_image(image_path: Path, out_path: Path) -> None:
    img = Image.open(image_path).convert("RGB")
    enhanced = ImageEnhance.Color(img).enhance(1.2)
    enhanced = enhanced.filter(ImageFilter.DETAIL)
    enhanced.save(out_path, format="JPEG", quality=92)
