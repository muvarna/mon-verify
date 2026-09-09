from __future__ import annotations

import requests

from monverify.clients.common import APIRequestError, request_json


class FakeSession:
    def __init__(self, responses: list[requests.Response]):
        self.responses = responses
        self.calls = 0

    def request(self, *args, **kwargs):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def make_response(status: int, body: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    response.url = "https://api.example.test/resource"
    return response


def test_401_is_not_retried():
    session = FakeSession([make_response(401, '{"message":"Unauthorized"}')])

    try:
        request_json(session, "GET", "https://api.example.test/resource", max_attempts=5)
    except APIRequestError as exc:
        assert exc.status_code == 401
        assert exc.detail == "Unauthorized"
    else:
        raise AssertionError("APIRequestError was not raised")

    assert session.calls == 1


def test_403_is_not_retried():
    session = FakeSession([make_response(403, '{"message":"Forbidden"}')])

    try:
        request_json(session, "GET", "https://api.example.test/resource", max_attempts=5)
    except APIRequestError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("APIRequestError was not raised")

    assert session.calls == 1
