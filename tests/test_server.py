"""Unit tests for the dev server's pure functions (no HTTP)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestReloadInjection(unittest.TestCase):
    def test_injects_before_body_close(self):
        body = b"<html><body><h1>hi</h1></body></html>"
        injected = lintc.inject_livereload(body)
        self.assertIn(b"EventSource", injected)
        # Inserted before </body>.
        self.assertLess(injected.index(b"EventSource"), injected.index(b"</body>"))

    def test_appends_if_no_body_tag(self):
        body = b"<h1>raw</h1>"
        injected = lintc.inject_livereload(body)
        self.assertIn(b"EventSource", injected)

    def test_no_inject_when_disabled(self):
        body = b"<html><body></body></html>"
        injected = lintc.inject_livereload(body, enabled=False)
        self.assertEqual(injected, body)


import threading
import time


class TestReloader(unittest.TestCase):
    def test_bump_advances_generation(self):
        r = lintc.Reloader()
        gen = r.current()
        r.bump_reload()
        self.assertGreater(r.current(), gen)

    def test_wait_unblocks_on_bump(self):
        r = lintc.Reloader()
        results = []

        def waiter():
            results.append(r.wait_past(0, timeout=2.0))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        r.bump_reload()
        t.join(timeout=3.0)
        self.assertEqual(len(results), 1)
        self.assertGreater(results[0][0], 0)

    def test_error_event_carries_payload(self):
        r = lintc.Reloader()
        r.set_error({"title": "Build error", "detail": "foo.md:3 something"})
        gen, kind, payload = r.snapshot()
        self.assertEqual(kind, "error-overlay")
        self.assertEqual(payload["title"], "Build error")
        r.clear_error()
        gen, kind, payload = r.snapshot()
        self.assertEqual(kind, "clear-overlay")


import io


class TestHTTPServerErrorHandling(unittest.TestCase):
    """LintcHTTPServer.handle_error suppresses tracebacks for client-disconnect
    errors and falls through to the default handler for anything else."""

    def _trigger(self, exc):
        """Build a server stub, raise exc inside a try/except so sys.exc_info()
        is populated, then call handle_error. Returns whatever was written to
        stderr."""
        # Don't bind a socket — we only need the method, not a live server.
        server = lintc.LintcHTTPServer.__new__(lintc.LintcHTTPServer)
        captured = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            try:
                raise exc
            except Exception:
                server.handle_error(request=None, client_address=("127.0.0.1", 54321))
        finally:
            sys.stderr = original_stderr
        return captured.getvalue()

    def test_connection_reset_suppressed_to_one_line(self):
        out = self._trigger(ConnectionResetError("[Errno 54] Connection reset by peer"))
        # One-line friendly message, not a multi-line traceback.
        self.assertIn("client 127.0.0.1:54321 disconnected", out)
        self.assertIn("ConnectionResetError", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(out.count("\n"), 1)

    def test_broken_pipe_suppressed_to_one_line(self):
        out = self._trigger(BrokenPipeError("[Errno 32] Broken pipe"))
        self.assertIn("BrokenPipeError", out)
        self.assertNotIn("Traceback", out)

    def test_connection_aborted_suppressed(self):
        out = self._trigger(ConnectionAbortedError("[Errno 53] Software caused connection abort"))
        self.assertIn("ConnectionAbortedError", out)
        self.assertNotIn("Traceback", out)

    def test_unrelated_exception_falls_through_to_default(self):
        # A ValueError should NOT be silenced — it would indicate a real bug.
        out = self._trigger(ValueError("kaboom"))
        # Default socketserver.handle_error prints a Traceback header.
        self.assertIn("Traceback", out)
        self.assertIn("kaboom", out)


if __name__ == "__main__":
    unittest.main()
