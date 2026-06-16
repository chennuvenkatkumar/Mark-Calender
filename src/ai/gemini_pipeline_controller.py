"""Gemini pipeline controller for syllabus extraction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


# Gemini model used when the caller does not override the model name
DEFAULT_MODEL = "gemini-1.5-flash"

# Strict prompt that instructs Gemini to return only a JSON array — no markdown,
# no prose — containing one object per academic event found in the syllabus.
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
    """Structural interface for injecting a custom Gemini client in tests.

    Any object that implements a `generate(prompt, model)` method satisfies
    this protocol and can be passed as the `client` argument to
    GeminiPipelineController without subclassing.
    """

    def generate(self, prompt: str, model: str) -> str:
        """Return the raw model response text for the given prompt."""


@dataclass(slots=True)
class GeminiPipelineController:
    """Thin wrapper around the Gemini API call.

    Orchestrates prompt construction and model invocation.  Supports two
    execution paths:
      - Injected client (used in tests via the GeminiClient protocol)
      - Direct SDK call (production path using google-genai)

    Attributes:
        api_key: Gemini API key. Falls back to GOOGLE_API_KEY / GEMINI_API_KEY
                 environment variables when not provided.
        model:   Gemini model identifier string (default: gemini-1.5-flash).
        client:  Optional injected client object that satisfies GeminiClient.
    """

    api_key: str | None = None
    model: str = DEFAULT_MODEL
    client: object | None = None

    def build_prompt(self, syllabus_text: str) -> str:
        """Inject the raw syllabus text into the extraction prompt template.

        Strips leading/trailing whitespace from the syllabus before insertion
        to avoid confusing the model with blank lines at the boundaries.

        Usage:
            prompt = controller.build_prompt(raw_text)
        """
        return PROMPT_TEMPLATE.format(syllabus_text=syllabus_text.strip())

    def generate(self, syllabus_text: str) -> str:
        """Build the prompt and call Gemini, returning the raw response text.

        Selects the injected client path when `self.client` is set; otherwise
        falls back to the SDK path which reads credentials from the environment.

        Usage:
            raw_json = controller.generate(syllabus_text)
        """
        prompt = self.build_prompt(syllabus_text)

        # Use the injected client (test doubles, custom wrappers) when available
        if self.client is not None:
            return self._generate_with_client(prompt)

        # Production path: call the Google Gen AI SDK directly
        return self._generate_with_sdk(prompt)

    def _generate_with_client(self, prompt: str) -> str:
        """Dispatch a generation call to the injected client object.

        Supports two common client shapes:
          1. Objects with a plain `generate(prompt, model)` callable —
             used by test doubles following the GeminiClient protocol.
          2. Objects with a `models.generate_content(model, contents)` method —
             matches the real google-genai Client surface, allowing injection of
             a pre-configured SDK client instance.

        Raises TypeError if the injected object matches neither shape.
        """

        # Shape 1: protocol-compliant test double with a top-level `generate` method
        generator = getattr(self.client, "generate", None)
        if callable(generator):
            return generator(prompt=prompt, model=self.model)

        # Shape 2: real SDK Client object with a `models` sub-resource
        model = getattr(self.client, "models", None)
        if model is not None and hasattr(model, "generate_content"):
            response = model.generate_content(model=self.model, contents=prompt)
            # `response.text` may be None if the model returned no candidates
            return getattr(response, "text", "") or ""

        raise TypeError("Unsupported Gemini client interface.")

    def _generate_with_sdk(self, prompt: str) -> str:
        """Call the Google Gen AI SDK directly using a resolved API key.

        Key resolution order:
          1. `self.api_key` set on the controller instance
          2. GOOGLE_API_KEY environment variable
          3. GEMINI_API_KEY environment variable

        Raises ValueError when no key is found and ImportError when the
        'google-genai' package is not installed.
        """

        # Resolve the API key from instance attribute or environment variables
        api_key = self.api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("A Gemini API key is required. Set GOOGLE_API_KEY or GEMINI_API_KEY.")

        # Guard against missing optional dependency — give a clear install hint
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise ImportError(
                "Google Gen AI SDK is required. Install the 'google-genai' package."
            ) from exc

        # Instantiate a fresh SDK client and call the model with the full prompt
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)

        # `response.text` is None when the model returns an empty candidates list
        return getattr(response, "text", "") or ""
