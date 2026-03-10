"""LLM-based script translation service using Amazon Bedrock Nova."""

from __future__ import annotations

import json
import logging
from typing import Sequence

logger = logging.getLogger(__name__)


class TranslationService:
    """Translate script lines using Amazon Bedrock Nova."""

    def __init__(self, bedrock_client, model_id: str, *, use_mock_ai: bool = False):
        self._client = bedrock_client
        self._model_id = model_id
        self._use_mock_ai = use_mock_ai

    def translate_script(
        self,
        script_lines: list[str],
        source_language: str,
        target_language: str,
        product_context: str,
    ) -> list[str]:
        """Translate script lines while preserving marketing tone and product terms.

        Args:
            script_lines: Original narration lines to translate.
            source_language: ISO 639-1 code of the source language (e.g. 'en').
            target_language: ISO 639-1 code of the target language (e.g. 'es').
            product_context: Product title/description for context.

        Returns:
            Translated script lines (same count as input).
        """
        if self._use_mock_ai:
            return [f'MOCK-TRANSLATE::{target_language}::{line}' for line in script_lines]

        prompt = self._build_prompt(script_lines, source_language, target_language, product_context)
        translated = self._call_llm(prompt, len(script_lines))
        return translated

    def _build_prompt(
        self,
        script_lines: list[str],
        source_language: str,
        target_language: str,
        product_context: str,
    ) -> str:
        from app.config.languages import get_language_name
        source_name = get_language_name(source_language)
        target_name = get_language_name(target_language)
        numbered_lines = '\n'.join(f'{i+1}. {line}' for i, line in enumerate(script_lines))
        return f"""You are a professional marketing translator. Translate the following video narration script
from {source_name} to {target_name}.

RULES:
- Keep product names, brand names, and model numbers UNTRANSLATED
- Preserve the marketing tone, urgency, and persuasion techniques
- Maintain the exact same number of lines ({len(script_lines)} lines)
- Adjust content length if the target language naturally expands (e.g. German ~30%% longer — shorten the message slightly)
- Each line should work as a standalone voiceover narration segment
- Do NOT add line numbers in the output

PRODUCT CONTEXT: {product_context}

SCRIPT TO TRANSLATE:
{numbered_lines}

OUTPUT: Return ONLY the translated lines, one per line, no numbering, no extra text."""

    def _call_llm(self, prompt: str, expected_line_count: int) -> list[str]:
        """Call Bedrock Nova to translate the script using the converse() API."""
        response = self._client.converse(
            modelId=self._model_id,
            messages=[
                {'role': 'user', 'content': [{'text': prompt}]},
            ],
            inferenceConfig={
                'maxTokens': 2000,
                'temperature': 0.3,
            },
        )

        raw_text = response['output']['message']['content'][0]['text'].strip()

        # Parse lines and ensure count matches
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]

        # Strip any accidental numbering (e.g. "1. ..." or "1) ...")
        import re
        cleaned: list[str] = []
        for line in lines:
            cleaned_line = re.sub(r'^\d+[\.\)\-]\s*', '', line).strip()
            if cleaned_line:
                cleaned.append(cleaned_line)

        # Ensure we return the exact expected count
        if len(cleaned) < expected_line_count:
            # Pad with empty strings if LLM returned fewer lines
            cleaned.extend([''] * (expected_line_count - len(cleaned)))
        elif len(cleaned) > expected_line_count:
            # Truncate if LLM returned extra lines
            cleaned = cleaned[:expected_line_count]

        return cleaned
