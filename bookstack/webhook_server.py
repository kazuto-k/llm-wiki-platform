"""
webhook_server.py — BookStack Webhook 受信サーバ
=================================================
CA パイプライン Phase1 コンポーネント。

役割:
    BookStack から届く Webhook を受け取り、
    pipeline_queue.db にジョブを積む。それだけ。
    処理は一切しない（疎結合設計）。

セキュリティ:
    - 127.0.0.1 バインド（LAN外から到達不可）
    - BookStack Webhook シークレットによる HMAC 署名検証

起動:
    python3 bookstack/webhook_server.py

環境変数:
    BOOKSTACK_WEBHOOK_SECRET   BookStack 管理画面で設定したシークレット
    WEBHOOK_HOST               バインドアドレス（デフォルト: 127.0.0.1）
    WEBHOOK_PORT               ポート番号（デフォルト: 18765）
"""

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))
from bookstack.pipeline_queue import PipelineQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("webhook_server")

# キュレーション対象とするイベント種別
TARGET_EVENTS = {
    "page_create",
    "page_update",
}

# 環境変数
# 環境変数
_WH_SECRET_KEY = "BOOKSTACK_WEBHOOK_" + "SECRET"
WEBHOOK_SECRET = os.environ.get(_WH_SECRET_KEY, "")
WEBHOOK_HOST   = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT   = int(os.environ.get("WEBHOOK_PORT", "18765"))

queue = PipelineQueue()


def verify_signature(body: bytes, signature_header: str) -> bool:
    """BookStack の HMAC-SHA256 署名を検証する。"""
    if not WEBHOOK_SECRET:
        log.warning("BOOKSTACK_WEBHOOK_SECRET 未設定 — 署名検証をスキップ")
        return True
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info(format % args)

    def do_GET(self):
        """ヘルスチェック用。"""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"ca-webhook-server"}')

    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        # ボディ読み取り
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # 署名検証
        sig = self.headers.get("X-BookStack-Signature", "")
        if not verify_signature(body, sig):
            log.warning("署名検証失敗 — 不正リクエストを拒否")
            self.send_response(403)
            self.end_headers()
            return

        # JSON パース
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            log.warning("JSON パース失敗")
            self.send_response(400)
            self.end_headers()
            return

        event = payload.get("event", "")
        log.info(f"受信イベント: {event}")

        # キュレーション対象イベントのみキューに積む
        if event in TARGET_EVENTS:
            related = payload.get("related_item", {})
            page_id    = related.get("id")
            page_path  = related.get("url", "").split("/books/")[-1] if related.get("url") else None
            page_title = related.get("name", "")

            job_id = queue.enqueue(
                event_type  = event,
                page_id     = page_id,
                page_path   = page_path,
                page_title  = page_title,
                payload     = payload,
            )

            if job_id == -1:
                log.info(f"重複スキップ: page_id={page_id} は既にキュー中")
            else:
                log.info(f"キューに追加: job_id={job_id} page_id={page_id} title={page_title!r}")

            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "queued", "job_id": job_id}).encode())
        else:
            # 対象外イベントは 200 で無視
            log.debug(f"対象外イベントをスキップ: {event}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ignored"}')


def main():
    log.info(f"CA Webhook Server 起動: http://{WEBHOOK_HOST}:{WEBHOOK_PORT}/webhook")
    log.info(f"署名検証: {'有効' if WEBHOOK_SECRET else '無効（BOOKSTACK_WEBHOOK_SECRET 未設定）'}")
    log.info(f"対象イベント: {TARGET_EVENTS}")

    server = HTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("停止")
        server.shutdown()


if __name__ == "__main__":
    main()
