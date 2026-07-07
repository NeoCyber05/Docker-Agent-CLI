"""Convert pydantic models to OpenAI / Gemini function declarations.

Parity: ``src/services/api/toolSchema.ts``.
"""

from __future__ import annotations

import types
import typing
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from infra_agent.services.api.types import ToolSchema

JsonSchemaNode = dict[str, Any]


def _is_optional(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    return origin in (typing.Union, types.UnionType) and type(None) in args


def _field_required(field: FieldInfo) -> bool:
    if field.is_required():
        return True
    annotation = field.annotation
    if annotation is not None and _is_optional(annotation):
        return False
    has_default = field.default is not PydanticUndefined or field.default_factory is not None
    return has_default


def to_json_schema(model: type[BaseModel]) -> JsonSchemaNode:
    """Convert a pydantic v2 model to a JSON schema node."""
    properties: dict[str, JsonSchemaNode] = {}
    required: list[str] = []
    for name, field_info in model.model_fields.items():
        properties[name] = _field_to_json_schema(field_info)
        if _field_required(field_info):
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _field_to_json_schema(field_info: FieldInfo) -> JsonSchemaNode:
    annotation = field_info.annotation
    if annotation is None:
        return {}
    return _type_to_json_schema(annotation)


def _type_to_json_schema(annotation: Any) -> JsonSchemaNode:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    if origin is list or annotation is list:
        items = _type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}

    if origin is dict or annotation is dict:
        return {"type": "object"}

    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_json_schema(non_none[0])
        return {"oneOf": [_type_to_json_schema(a) for a in non_none]}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return to_json_schema(annotation)

    if origin is typing.Literal:
        return {"type": "string", "enum": list(args)}

    return {}


def to_openai_function(tool: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": to_json_schema(tool.input_schema),
        },
    }


def strip_for_gemini(node: JsonSchemaNode) -> JsonSchemaNode:
    result = {k: v for k, v in node.items() if k not in ("additionalProperties", "oneOf")}
    if "properties" in result:
        result["properties"] = {
            k: strip_for_gemini(v) for k, v in result["properties"].items()
        }
    if "items" in result:
        result["items"] = strip_for_gemini(result["items"])
    return result


def to_gemini_function_declaration(tool: ToolSchema) -> dict[str, Any]:
    parameters = strip_for_gemini(to_json_schema(tool.input_schema))
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": parameters,
    }


__all__ = [
    "strip_for_gemini",
    "to_gemini_function_declaration",
    "to_json_schema",
    "to_openai_function",
]