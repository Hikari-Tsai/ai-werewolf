"""Cloudflare 快速隧道：把本機的伺服器開成一個公開網址，不需要固定 IP、不用開 port。

- 先找 PATH 和專案的 bin/ 有沒有 cloudflared
- 沒有就問一聲，從 Cloudflare 官方 GitHub release 下載到 bin/
- 啟動後從輸出抓 https://xxx.trycloudflare.com，寫進 config.PUBLIC_URL，前端會顯示
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import urllib.request

from . import config

BIN_DIR = os.path.join(config.ROOT, "bin")
RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
ASSETS = {
    ("Windows", "AMD64"): "cloudflared-windows-amd64.exe",
    ("Windows", "ARM64"): "cloudflared-windows-arm64.exe",
    ("Darwin", "arm64"): "cloudflared-darwin-arm64.tgz",
    ("Darwin", "x86_64"): "cloudflared-darwin-amd64.tgz",
    ("Linux", "x86_64"): "cloudflared-linux-amd64",
    ("Linux", "aarch64"): "cloudflared-linux-arm64",
}


def find_binary() -> str | None:
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    local = os.path.join(BIN_DIR, "cloudflared.exe" if os.name == "nt" else "cloudflared")
    return local if os.path.exists(local) else None


def install(auto_yes: bool = False) -> str | None:
    key = (platform.system(), platform.machine())
    asset = ASSETS.get(key)
    if not asset:
        print(f"不知道 {key} 要下載哪個 cloudflared，請自行安裝：https://github.com/cloudflare/cloudflared/releases")
        return None
    if not auto_yes:
        ans = input(f"找不到 cloudflared，要從 Cloudflare 官方 release 下載 {asset} 到 bin/ 嗎？[Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            return None
    os.makedirs(BIN_DIR, exist_ok=True)
    url = RELEASE + asset
    target = os.path.join(BIN_DIR, "cloudflared.exe" if os.name == "nt" else "cloudflared")
    print(f"下載中：{url}")
    tmp = target + ".download"
    urllib.request.urlretrieve(url, tmp)
    if asset.endswith(".tgz"):
        import tarfile
        with tarfile.open(tmp) as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith("cloudflared"))
            member.name = os.path.basename(target)
            tf.extract(member, BIN_DIR)
        os.remove(tmp)
    else:
        os.replace(tmp, target)
    if os.name != "nt":
        os.chmod(target, 0o755)
    print(f"已安裝到 {target}")
    return target


def start(port: int, on_url, auto_install: bool = False) -> subprocess.Popen | None:
    """啟動隧道；拿到公開網址時呼叫 on_url(url)。回傳子程序，關閉時 terminate()。"""
    exe = find_binary() or install(auto_install)
    if not exe:
        print("沒有 cloudflared，略過隧道。")
        return None
    # 公司網路常有 TLS 攔截代理，憑證序號是負數會被 Go 拒絕；這個開關讓 cloudflared 接受它
    env = {**os.environ, "GODEBUG": (os.environ.get("GODEBUG", "") + ",x509negativeserial=1").strip(",")}
    proc = subprocess.Popen([exe, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env=env)

    def reader():
        for line in proc.stdout:
            # cloudflared 的 log 會先提到 api.trycloudflare.com，那不是隧道網址
            m = re.search(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not config.PUBLIC_URL:
                config.PUBLIC_URL = m.group(0)
                on_url(config.PUBLIC_URL)
        if proc.returncode not in (None, 0):
            print("cloudflared 結束了，公開網址失效。", file=sys.stderr)
        config.PUBLIC_URL = ""

    threading.Thread(target=reader, daemon=True).start()
    return proc
