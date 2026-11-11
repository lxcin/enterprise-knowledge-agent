import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from knowledge_agent.model import ChatModel, ModelError


class ModelAdapterTests(unittest.TestCase):
    def test_transport_errors_have_distinct_codes(self):
        cases = [
            (TimeoutError(), "timeout"),
            (URLError(TimeoutError()), "timeout"),
            (URLError("offline"), "network_error"),
            (ConnectionResetError(), "network_error"),
            (HTTPError("https://example.invalid", 429, "rate limit", {}, None), "http_error"),
        ]
        for error, code in cases:
            with self.subTest(code=code):
                with patch("knowledge_agent.model.urlopen", side_effect=error) as call:
                    with self.assertRaises(ModelError) as caught:
                        ChatModel("https://example.invalid", "test").decide("JSON", {}, [])
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(call.call_count, 1)

    def test_response_failures_are_separate_from_network_errors(self):
        cases = [
            ({"choices": []}, "invalid_response"),
            ({"choices": [{"message": {"content": " "}}]}, "empty_response"),
            ({"choices": [{"message": {"content": "{bad"}}]}, "invalid_json"),
            ({"choices": [{"message": {"content": "[]"}}]}, "invalid_action"),
            ({"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]},
             "truncated_response"),
        ]
        for response, code in cases:
            with self.subTest(code=code):
                with patch("knowledge_agent.model.urlopen",
                           return_value=io.BytesIO(json.dumps(response).encode())):
                    with self.assertRaises(ModelError) as caught:
                        ChatModel("https://example.invalid", "test").decide("JSON", {}, [])
                self.assertEqual(caught.exception.code, code)

    def test_valid_decision_is_returned(self):
        body = {"choices": [{"message": {"content": '{"action":"search","query":"报销"}'},
                             "finish_reason": "stop"}]}
        with patch("knowledge_agent.model.urlopen",
                   return_value=io.BytesIO(json.dumps(body).encode())):
            result = ChatModel("https://example.invalid", "test").decide("JSON", {}, [])
        self.assertEqual(result, {"action": "search", "query": "报销"})
