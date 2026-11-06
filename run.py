"""啟動：python run.py [--port 8000] [--tunnel]

印出區網網址與 QR code；--tunnel 會用 cloudflared 開一條公開隧道。
"""
import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def show(url: str, label: str, qr: bool = True):
    print(f"{label}：{url}")
    if not qr:
        return
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(url)
        q.print_ascii(invert=True)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--tunnel", action="store_true", help="用 cloudflared 開公開隧道（沒裝會問要不要下載）")
    ap.add_argument("--yes", action="store_true", help="不問，直接下載 cloudflared")
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    from server.ai.llm import router
    from server import tunnel as tunnel_mod
    if not router.available():
        print("注意：.env 沒有任何 API key，只能全真人玩")

    show(f"http://{lan_ip()}:{args.port}", "本地", qr=not args.tunnel)
    tunnel = tunnel_mod.start(args.port, lambda url: show(url, "通道"), auto_install=args.yes) if args.tunnel else None
    try:
        import uvicorn
        uvicorn.run("server.app:app", host="0.0.0.0", port=args.port, reload=args.reload,
                    log_level="warning", access_log=False)
    finally:
        if tunnel:
            tunnel.terminate()


if __name__ == "__main__":
    main()
