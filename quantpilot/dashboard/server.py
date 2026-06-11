"""MINCODE 대시보드 로컬 HTTP 서버 (stdlib만 사용).

라우트:
  GET  /            → static/index.html
  GET  /static/...  → 프런트 자산(js)
  GET  /api/state   → build_state JSON (요청마다 fresh 세션 — 루프의 커밋을 즉시 반영)
  POST /api/panic   → ops.execute_panic (CLI panic과 동일 코드 경로)

WHY 127.0.0.1 기본: 킬스위치 쓰기 엔드포인트가 있으므로 외부 노출 금지.
WHY 요청마다 새 세션: 도는 루프가 다른 프로세스에서 commit하므로, 세션을 오래 들고
있으면 캐시된 과거 상태를 보게 된다(expire 문제). 짧은 세션이 가장 단순·정확.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quantpilot.dashboard.api import build_state
from quantpilot.paper.ops import PanicError, execute_panic

STATIC_DIR = Path(__file__).parent / "static"
_MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".jsx": "text/babel; charset=utf-8", ".css": "text/css; charset=utf-8"}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, session_factory, *, symbol, timeframe, strategy,
                 log_dir="logs"):
        super().__init__(addr, _Handler)
        self.session_factory = session_factory
        self.cfg = {"symbol": symbol, "timeframe": timeframe, "strategy": strategy,
                    "log_dir": log_dir}
        # 마지막 성공 응답 캐시: 루프의 큰 commit과 겹쳐 SQLite lock이 나면 stale로 응답.
        self._last_good: bytes | None = None
        self._lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, *args):    # 요청 로그로 터미널 오염 방지
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            cfg = self.server.cfg
            try:
                session = self.server.session_factory()
                try:
                    state = build_state(session, symbol=cfg["symbol"],
                                        timeframe=cfg["timeframe"],
                                        strategy=cfg["strategy"],
                                        log_dir=cfg["log_dir"])
                finally:
                    session.close()
                body = json.dumps(state).encode()
                with self.server._lock:
                    self.server._last_good = body
                self._send(200, body)
            except Exception as e:                          # lock 등 일시 오류 → stale 응답
                with self.server._lock:
                    stale = self.server._last_good
                if stale is not None:
                    self._send(200, stale)
                else:
                    self._send_json(503, {"error": str(e)})
            return
        if path == "/":
            path = "/index.html"
        # static 파일 (디렉토리 탈출 방지)
        rel = path.lstrip("/").removeprefix("static/")
        f = (STATIC_DIR / rel).resolve()
        if not str(f).startswith(str(STATIC_DIR.resolve())) or not f.is_file():
            self._send_json(404, {"error": "not found"})
            return
        self._send(200, f.read_bytes(), _MIME.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        if self.path.split("?")[0] != "/api/panic":
            self._send_json(404, {"error": "not found"})
            return
        cfg = self.server.cfg
        session = self.server.session_factory()
        try:
            r = execute_panic(session, cfg["symbol"], cfg["timeframe"], cfg["strategy"])
            self._send_json(200, {"ok": True, "had_position": r.had_position,
                                  "pnl_net": r.pnl_net, "equity": r.equity})
        except PanicError as e:
            self._send_json(409, {"ok": False, "error": str(e)})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})
        finally:
            session.close()


def make_server(session_factory, *, symbol="BTC-USDT-SWAP", timeframe="1h",
                strategy="rsi-mr", host="127.0.0.1", port=8787,
                log_dir="logs") -> DashboardServer:
    return DashboardServer((host, port), session_factory, symbol=symbol,
                           timeframe=timeframe, strategy=strategy, log_dir=log_dir)
