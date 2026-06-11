import pytest
from fastapi.testclient import TestClient
import os
os.environ["ENABLE_STUB"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""
from app.main import app
import asyncio
from app.tools import calculator, get_current_datetime, word_counter, unit_converter, json_formatter

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# Health 

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["uptime_seconds"] >= 0


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "service" in r.json()


# ask 

def test_ask_basic(client):
    r = client.post("/ask", json={"question": "Hello, who are you?"})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "request_id" in body
    assert "session_id" in body
    assert isinstance(body["reasoning_steps"], list)
    assert isinstance(body["tools_used"], list)
    assert body["latency_ms"] >= 0


def test_ask_calculator_stub(client):
    r = client.post("/ask", json={"question": "Calculate 10 + 5"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    # In stub mode a calculator tool should be recorded
    assert any(t["name"] == "calculator" for t in body["tools_used"])


def test_ask_datetime_stub(client):
    r = client.post("/ask", json={"question": "What is today's date?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]


def test_ask_missing_question(client):
    r = client.post("/ask", json={})
    assert r.status_code == 422          # validation error


def test_ask_empty_question(client):
    r = client.post("/ask", json={"question": ""})
    assert r.status_code == 422


def test_ask_session_passthrough(client):
    """Session ID provided by caller should be echoed back."""
    r = client.post("/ask", json={"question": "Hi", "session_id": "test-session-123"})
    assert r.status_code == 200
    assert r.json()["session_id"] == "test-session-123"


def test_response_time_header(client):
    r = client.post("/ask", json={"question": "Ping"})
    assert "x-response-time-ms" in r.headers


# Tool implementations 


def test_tool_calculator_valid():
    result = asyncio.run(calculator({"expression": "2 + 2"}))
    assert result["result"] == 4


def test_tool_calculator_invalid():
    result = asyncio.run(calculator({"expression": "import os"}))
    assert "error" in result


def test_tool_datetime():
    result = asyncio.run(get_current_datetime({"format": "iso"}))
    assert "datetime" in result


def test_tool_word_counter():
    result = asyncio.run(word_counter({"text": "Hello world this is a test"}))
    assert result["words"] == 6


def test_tool_unit_converter_km_miles():
    result = asyncio.run(unit_converter({"value": 100, "from_unit": "km", "to_unit": "miles"}))
    assert abs(float(result["output"].split()[0]) - 62.1371) < 0.01


def test_tool_unit_converter_celsius_fahrenheit():
    result = asyncio.run(unit_converter({"value": 0, "from_unit": "celsius", "to_unit": "fahrenheit"}))
    assert float(result["output"].split()[0]) == 32.0


def test_tool_json_formatter_valid():
    result = asyncio.run(json_formatter({"json_string": '{"a": 1, "b": 2}'}))
    assert "formatted" in result
    assert result["keys"] == ["a", "b"]


def test_tool_json_formatter_invalid():
    result = asyncio.run(json_formatter({"json_string": "not json"}))
    assert "error" in result
