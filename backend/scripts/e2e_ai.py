"""The end-to-end tests' AI (scripts/e2e_server.py puts it in place of the real
one). It answers formatting instructions of two fixed kinds the way the real
model does -- operations on the elements the prompt lists:

    delete “<the start of a block's text>”
    make the title red

(joined with "and" if both). Everything else -- other instructions, structure
analysis, style analysis -- fails as if no AI key were set, so every other flow
takes its fallback exactly as without this."""

import ast
import re
from typing import TypeVar

from pydantic import BaseModel

from app.ai.base import AIProvider
from app.ai.schemas import AIDocumentOperation, AIInstructionExtractionResponse

T = TypeVar("T", bound=BaseModel)

_ELEMENT = re.compile(r"^- id=(\S+) type=(\S+) text=(.*)$", re.MULTILINE)
_INSTRUCTIONS = re.compile(r"<instructions>\n(.*)\n</instructions>", re.DOTALL)
_DELETE = re.compile(r"delete\s+[“\"]([^”\"]+)[”\"]", re.IGNORECASE)
_NO_AI = "Could not resolve authentication method (end-to-end tests: no AI for this)."


class E2EAIProvider(AIProvider):
    def provider_name(self) -> str:
        return "e2e"

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        raise TypeError(_NO_AI)

    async def complete_structured(self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None) -> T:
        instructions = _INSTRUCTIONS.search(prompt)
        if response_model is not AIInstructionExtractionResponse or instructions is None:
            raise TypeError(_NO_AI)
        elements = [(element_id, kind, ast.literal_eval(text)) for element_id, kind, text in _ELEMENT.findall(prompt)]
        text = instructions.group(1)
        operations: list[AIDocumentOperation] = []
        for start in _DELETE.findall(text):
            target = next((element_id for element_id, _, content in elements if content.startswith(start)), None)
            if target:
                operations.append(AIDocumentOperation(op="delete_element", element_id=target))
        if "make the title red" in text.lower():
            heading = next((element_id for element_id, kind, _ in elements if kind == "heading"), None)
            if heading:
                operations.append(AIDocumentOperation(op="set_style", element_id=heading, property="color", value="red"))
        if not operations:
            raise TypeError(_NO_AI)
        return AIInstructionExtractionResponse(operations=operations)  # type: ignore[return-value]
