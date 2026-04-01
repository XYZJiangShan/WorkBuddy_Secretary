"""
test_wxwork_doc.py - 测试企业微信文档 Cookie 读取（无需管理员权限版）
"""
import sys, os, re, shutil, sqlite3, json, tempfile
from pathlib import Path

def get_chrome_cookies_manual():
    """直接复制 Chrome Cookie 数据库文件读取（不需要管理员权限）"""
    possible_paths = [
        Path(os.environ.get("LOCALAPPDATA","")) / "Google/Chrome/User Data/Default/Network/Cookies",
        Path(os.environ.get("LOCALAPPDATA","")) / "Google/Chrome/User Data/Default/Cookies",
        Path(os.environ.get("LOCALAPPDATA","")) / "Microsoft/Edge/User Data/Default/Network/Cookies",
        Path(os.environ.get("LOCALAPPDATA","")) / "Microsoft/Edge/User Data/Default/Cookies",
    ]
    for p in possible_paths:
        if p.exists():
            print(f"  Found: {p}")
            # 复制到临时文件（原文件被浏览器锁定）
            tmp = tempfile.mktemp(suffix=".db")
            try:
                shutil.copy2(str(p), tmp)
                conn = sqlite3.connect(tmp)
                conn.row_factory = sqlite3.Row
                # Chrome 新版 Cookie 是加密的，只能读 host_key 和 name
                rows = conn.execute(
                    "SELECT host_key, name, value, encrypted_value FROM cookies WHERE host_key LIKE '%weixin.qq.com%'"
                ).fetchall()
                conn.close()
                os.unlink(tmp)
                if rows:
                    print(f"  Found {len(rows)} weixin cookies")
                    for r in rows[:5]:
                        print(f"    {r['host_key']} | {r['name']} | value_len={len(r['value'] or r['encrypted_value'])}")
                    return rows
                else:
                    print(f"  No weixin.qq.com cookies found in this profile")
            except Exception as e:
                print(f"  Error reading {p}: {e}")
    return None


def test_requests_with_manual_cookie(doc_url: str, cookie_str: str = None):
    """用手动提供的 Cookie 字符串测试文档访问"""
    import requests
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Referer": "https://doc.weixin.qq.com/",
    }
    if cookie_str:
        for item in cookie_str.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                session.cookies.set(k.strip(), v.strip(), domain=".weixin.qq.com")

    print(f"\nRequesting: {doc_url}")
    try:
        resp = session.get(doc_url, headers=headers, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Final URL: {resp.url}")
        if resp.status_code == 200:
            title_m = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE)
            if title_m:
                print(f"Title: {title_m.group(1)}")
            if "doc_name" in resp.text or "docContent" in resp.text:
                print("SUCCESS: Document content detected!")
                return True
            elif "login" in resp.url.lower() or "sso" in resp.url.lower():
                print("REDIRECT to login: Cookie invalid or expired")
            else:
                text_preview = re.sub(r"<[^>]+>", " ", resp.text[:1000])
                text_preview = re.sub(r"\s+", " ", text_preview)[:300]
                print(f"Content preview: {text_preview}")
        return False
    except Exception as e:
        print(f"Request failed: {e}")
        return False


if __name__ == "__main__":
    print("=== WxWork Doc Cookie Test ===")
    print("\n[Step 1] Checking Chrome/Edge cookie files...")
    rows = get_chrome_cookies_manual()
    
    if not rows:
        print("\nCannot read cookies directly.")
        print("Chrome cookies are encrypted with DPAPI in newer versions.")
    else:
        print("\nCookie file readable (but values may be encrypted).")
    
    if len(sys.argv) > 1:
        doc_url = sys.argv[1]
        cookie_str = sys.argv[2] if len(sys.argv) > 2 else None
        test_requests_with_manual_cookie(doc_url, cookie_str)
    else:
        print("\nUsage: py test_wxwork_doc.py <doc_url> [cookie_string]")
        print("Example: py test_wxwork_doc.py https://doc.weixin.qq.com/doc/w3_xxx")
