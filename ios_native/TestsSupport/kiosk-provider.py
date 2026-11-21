"""Deterministic OpenAI-compatible replies for the local simulator UI fixture."""
import io
import json
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Provider(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/audio/speech"):
            output = io.BytesIO()
            with wave.open(output, "wb") as sound:
                sound.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                sound.writeframes(bytes(6400))
            body = output.getvalue()
            content_type = "audio/wav"
        elif request.get("stream"):
            choices = [
                {"index": 0, "delta": {"role": "assistant", "content": "How long have you felt this way?"}},
                {"index": 0, "delta": {}, "finish_reason": "stop"},
            ]
            events = ["data: " + json.dumps({"choices": [choice]}) for choice in choices]
            body = ("\n\n".join(events + ["data: [DONE]", ""]) + "\n").encode()
            content_type = "text/event-stream"
        else:
            # Semantic detection stays neutral so the backend's real rule layer decides critical.
            reply = {"role": "assistant", "content": json.dumps({"alerts": [], "red_flags": []})}
            body = json.dumps({"choices": [{"index": 0, "message": reply, "finish_reason": "stop"}]}).encode()
            content_type = "application/json"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Provider).serve_forever()
