
"""Gemini pipeline controller for syllabus extraction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


DEFAULT_MODEL = "gemini-1.5-flash"

PROMPT_TEMPLATE = """You are a highly precise academic schedule data system.
Extract all exams, project deadlines, quizzes, and assignment tasks from the syllabus text
block below.
You must return data matching this JSON structural array. No explanations. No markdown
syntax wrapper block.
[
  {{
    "course_name": "Course Title here",
    "task_name": "Assignment/Exam Title here",
    "due_date": "YYYY-MM-DD",
    "due_time": "HH:MM",
    "description": "Short programmatic context or reading prerequisites"
  }}
]
Operational Rules:
1. Normalize all structural expressions of time to explicit ISO-8601 formatting.
2. If no time is explicitly stated, fallback strictly to "23:59".
3. If no calendar year is stated, assume the current operational year of 2026.
Syllabus Input:
{syllabus_text}
"""


class GeminiClient(Protocol):
    def generate(self, prompt: str, model: str) -> str:
        """Return the model response text."""


@dataclass(slots=True)
class GeminiPipelineController:
    """Thin wrapper around the Gemini API call."""

    api_key: str | None = None
    model: str = DEFAULT_MODEL
    client: object | None = None

    def build_prompt(self, syllabus_text: str) -> str:
        return PROMPT_TEMPLATE.format(syllabus_text=syllabus_text.strip())

    def generate(self, syllabus_text: str) -> str:
        prompt = self.build_prompt(syllabus_text)
        if self.client is not None:
            return self._generate_with_client(prompt)
        return self._generate_with_sdk(prompt)

    def _generate_with_client(self, prompt: str) -> str:
        generator = getattr(self.client, "generate", None)
        if callable(generator):
            return generator(prompt=prompt, model=self.model)

        model = getattr(self.client, "models", None)
        if model is not None and hasattr(model, "generate_content"):
            response = model.generate_content(model=self.model, contents=prompt)
            return getattr(response, "text", "") or ""

        raise TypeError("Unsupported Gemini client interface.")

    def _generate_with_sdk(self, prompt: str) -> str:
        api_key = self.api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("A Gemini API key is required. Set GOOGLE_API_KEY or GEMINI_API_KEY.")

        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise ImportError(
                "Google Gen AI SDK is required. Install the 'google-genai' package."
            ) from exc

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return getattr(response, "text", "") or ""
