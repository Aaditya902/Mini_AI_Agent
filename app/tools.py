import datetime
import json
import math
import re
from typing import Any, Callable


# Tool implementations (sync - no event loop needed)
def calculator(params: dict) -> dict:
    expression = params.get("expression", "")
    safe = expression.replace("sqrt", "").replace("**", "")
    if not re.match(r'^[\d\s\+\-\*\/\(\)\.\,\%\^\s]*$', safe):
        return {"error": "Unsafe expression — only basic math allowed"}
    try:
        sanitised = expression.replace("^", "**")
        result = eval(sanitised, {"__builtins__": {}, "sqrt": math.sqrt, "math": math})  # noqa: S307
        return {"result": result, "expression": expression}
    except Exception as e:
        return {"error": str(e)}


def get_current_datetime(params: dict) -> dict:
    fmt = params.get("format", "iso")
    now = datetime.datetime.now(datetime.timezone.utc)
    if fmt == "human":
        return {"datetime": now.strftime("%A, %B %d %Y at %H:%M UTC")}
    return {"datetime": now.isoformat(), "timestamp": int(now.timestamp())}


def word_counter(params: dict) -> dict:
    text: str = params.get("text", "")
    words = len(text.split())
    chars = len(text)
    sentences = len(re.findall(r'[.!?]+', text)) or 1
    return {
        "words": words,
        "characters": chars,
        "sentences": sentences,
        "avg_words_per_sentence": round(words / sentences, 1),
    }


def json_formatter(params: dict) -> dict:
    raw = params.get("json_string", "")
    try:
        parsed = json.loads(raw)
        return {
            "formatted": json.dumps(parsed, indent=2),
            "keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
        }
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}


def unit_converter(params: dict) -> dict:
    value = float(params.get("value", 0))
    from_unit = params.get("from_unit", "").lower()
    to_unit = params.get("to_unit", "").lower()

    conversions: dict[tuple, float] = {
        ("km", "miles"): 0.621371,
        ("miles", "km"): 1.60934,
        ("kg", "lbs"): 2.20462,
        ("lbs", "kg"): 0.453592,
        ("meters", "feet"): 3.28084,
        ("feet", "meters"): 0.3048,
    }

    key = (from_unit, to_unit)
    if key == ("celsius", "fahrenheit"):
        result = (value * 9 / 5) + 32
    elif key == ("fahrenheit", "celsius"):
        result = (value - 32) * 5 / 9
    elif key in conversions:
        result = value * conversions[key]
    else:
        return {"error": f"Unsupported conversion: {from_unit} → {to_unit}"}

    return {"input": f"{value} {from_unit}", "output": f"{round(result, 4)} {to_unit}"}


# Tool registry + JSON-schema descriptions

TOOLS: list[dict] = [
    {
        "name": "calculator",
        "description": "Evaluate a mathematical expression. Use for any numeric calculation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. '(3 + 4) * 8 / 2'"}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_current_datetime",
        "description": "Get the current UTC date and time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["iso", "human"], "description": "Output format"}
            },
            "required": [],
        },
    },
    {
        "name": "word_counter",
        "description": "Count words, characters, and sentences in a block of text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to analyse"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "json_formatter",
        "description": "Parse and pretty-print a JSON string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "json_string": {"type": "string", "description": "Raw JSON string to format"}
            },
            "required": ["json_string"],
        },
    },
    {
        "name": "unit_converter",
        "description": "Convert between units: km/miles, kg/lbs, celsius/fahrenheit, meters/feet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
    },
]

TOOL_FN_MAP: dict[str, Callable] = {
    "calculator": calculator,
    "get_current_datetime": get_current_datetime,
    "word_counter": word_counter,
    "json_formatter": json_formatter,
    "unit_converter": unit_converter,
}


def dispatch_tool(name: str, input_params: dict) -> Any:
    """Execute a tool by name and return its output. Fully synchronous."""
    fn = TOOL_FN_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    return fn(input_params)