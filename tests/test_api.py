import http.client
import io
import unittest
from unittest import mock

from aion2.api import ApiError, Client


class Retry(unittest.TestCase):
    def client(self):
        return Client("https://example.test/api", delay=0, retries=2)

    @mock.patch("aion2.api.time.sleep")
    def test_a_cut_off_response_is_retried(self, _sleep):
        responses = [http.client.IncompleteRead(b"{", 10), io.BytesIO(b'{"ok": true}')]

        def urlopen(*_a, **_k):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("aion2.api.urllib.request.urlopen", urlopen):
            self.assertEqual(self.client().get("/x"), {"ok": True})

    @mock.patch("aion2.api.time.sleep")
    def test_gives_up_after_the_retries(self, _sleep):
        with mock.patch("aion2.api.urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"", 5)):
            with self.assertRaises(ApiError):
                self.client().get("/x")


if __name__ == "__main__":
    unittest.main()
