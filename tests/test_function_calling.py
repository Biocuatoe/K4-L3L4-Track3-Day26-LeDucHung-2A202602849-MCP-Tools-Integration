"""Module 01 — dispatch, schema và vòng lặp function calling (model được giả lập)."""

import json

import pytest
from google.genai import types

import weather_function_calling as wfc


def model_reply(*, calls=None, text=None):
    parts = [types.Part.from_function_call(name=n, args=a) for n, a in (calls or [])]
    if text is not None:
        parts.append(types.Part.from_text(text=text))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


class FakeClient:
    """Trả lần lượt các phản hồi đã định sẵn; ghi lại contents mỗi lần gọi."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.seen.append(list(contents))
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


def test_schema_matches_implementation():
    decl = wfc.get_weather_declaration
    assert decl.name == "get_weather" == wfc.get_weather.__name__
    assert decl.parameters.required == ["city"]
    assert set(decl.parameters.properties) == {"city"}
    assert decl.parameters.properties["city"].type == types.Type.STRING


def test_get_weather_known_city_is_labelled_mock():
    data = json.loads(wfc.get_weather("Hà Nội"))
    assert data["city"] == "Hà Nội"
    assert data["nguồn"] == "mock"
    assert data["nhiệt_độ"] == "29°C"


def test_get_weather_unknown_city_uses_default():
    data = json.loads(wfc.get_weather("Atlantis"))
    assert data["thời_tiết"] == "không có dữ liệu chi tiết"


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_get_weather_rejects_invalid_city(bad):
    with pytest.raises(ValueError):
        wfc.get_weather(bad)


def test_execute_tool_call_success():
    out = wfc.execute_tool_call("get_weather", {"city": "Đà Nẵng"})
    assert json.loads(out["result"])["nhiệt_độ"] == "30°C"


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_everything", {"city": "x"}),  # tool lạ
        (None, {"city": "x"}),
        ("get_weather", {}),  # thiếu tham số
        ("get_weather", None),
        ("get_weather", {"city": "x", "extra": 1}),  # tham số thừa
        ("get_weather", {"city": ""}),  # giá trị sai -> lỗi trong tool
    ],
)
def test_execute_tool_call_errors_are_returned_not_raised(name, args):
    out = wfc.execute_tool_call(name, args)
    assert "error" in out and "result" not in out


def test_run_executes_tool_and_returns_final_text():
    client = FakeClient([
        model_reply(calls=[("get_weather", {"city": "Hà Nội"}), ("get_weather", {"city": "Đà Nẵng"})]),
        model_reply(text="Hà Nội mưa nhẹ, Đà Nẵng nhiều mây."),
    ])
    assert wfc.run("thời tiết?", client=client) == "Hà Nội mưa nhẹ, Đà Nẵng nhiều mây."
    # Lần gọi thứ hai phải chứa kết quả tool do APP thực thi
    responses = [p.function_response for c in client.seen[1] for p in c.parts if p.function_response]
    assert len(responses) == 2
    assert json.loads(responses[0].response["result"])["city"] == "Hà Nội"


def test_run_without_tool_call_returns_text():
    assert wfc.run("hi", client=FakeClient([model_reply(text="xin chào")])) == "xin chào"


def test_run_sends_tool_error_back_to_model():
    client = FakeClient([
        model_reply(calls=[("nope", {})]),
        model_reply(text="xin lỗi"),
    ])
    assert wfc.run("?", client=client) == "xin lỗi"
    resp = [p.function_response for c in client.seen[1] for p in c.parts if p.function_response][0]
    assert "error" in resp.response


def test_run_stops_endless_tool_loop():
    client = FakeClient([model_reply(calls=[("get_weather", {"city": "Hà Nội"})])])
    with pytest.raises(RuntimeError, match="vòng"):
        wfc.run("?", client=client, max_rounds=3)
    assert len(client.seen) == 4  # 1 lần đầu + 3 vòng, rồi dừng


def test_run_raises_on_empty_model_text():
    with pytest.raises(RuntimeError):
        wfc.run("?", client=FakeClient([model_reply()]))
