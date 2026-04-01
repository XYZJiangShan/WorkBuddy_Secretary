"""
services/wxwork_doc_service.py - 企业微信文档读取服务

通过用户手动提供的 Cookie（从浏览器 DevTools 复制）
读取企业微信文档内容，供 AI 分析使用。

Cookie 存储在 settings 表中（key: wxwork_cookie），
失效时提示用户重新获取。
"""
from __future__ import annotations

import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WxWorkDocInfo:
    """文档基本信息"""
    url: str
    title: str = ""
    content: str = ""       # 纯文本内容
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.content or self.title)


class WxWorkDocService:
    """
    企业微信文档读取服务

    使用方式：
        service = WxWorkDocService(settings_repo)
        info = service.fetch_doc("https://doc.weixin.qq.com/doc/w3_xxx")
        if info.success:
            print(info.title, info.content[:500])
    """

    SUPPORTED_HOSTS = [
        "doc.weixin.qq.com",
        "docs.weixin.qq.com",
        "kdocs.cn",            # 金山文档
        "feishu.cn",           # 飞书文档
        "larksuite.com",       # 飞书国际版
    ]

    def __init__(self, settings=None):
        self._settings = settings
        self._session = None

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def fetch_doc(self, url: str) -> WxWorkDocInfo:
        """
        获取文档内容（纯文本）。
        自动使用已保存的 Cookie，失效时返回错误信息。
        """
        info = WxWorkDocInfo(url=url)
        try:
            import requests
        except ImportError:
            info.error = "缺少依赖: py -m pip install requests"
            return info

        cookie_str = self._get_cookie()
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://doc.weixin.qq.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

        if cookie_str:
            for item in cookie_str.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    session.cookies.set(k.strip(), v.strip())

        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            logger.debug("Doc fetch: %s -> %d", url, resp.status_code)

            if resp.status_code != 200:
                info.error = f"请求失败 (HTTP {resp.status_code})"
                return info

            # 检测是否跳转到登录页
            if self._is_login_page(resp):
                info.error = "Cookie 已失效，请在设置中更新企微文档 Cookie"
                return info

            # 提取标题
            info.title = self._extract_title(resp.text)

            # 提取正文文本
            info.content = self._extract_text(resp.text, url)

            if not info.content and not info.title:
                info.error = "无法提取文档内容（可能需要登录或文档不公开）"

        except Exception as e:
            info.error = f"请求异常: {e}"
            logger.error("fetch_doc error: %s", e)

        return info

    def get_doc_title_only(self, url: str) -> str:
        """快速获取文档标题（用于链接预览）"""
        info = self.fetch_doc(url)
        return info.title or info.error or "（无法读取标题）"

    def is_wxwork_url(self, url: str) -> bool:
        """判断是否是支持的文档链接"""
        return any(host in url for host in self.SUPPORTED_HOSTS)

    # ------------------------------------------------------------------ #
    #  Cookie 管理
    # ------------------------------------------------------------------ #

    def save_cookie(self, cookie_str: str) -> None:
        """保存 Cookie 到 settings"""
        if self._settings:
            self._settings.set("wxwork_cookie", cookie_str.strip())
            logger.info("WxWork cookie saved")

    def _get_cookie(self) -> str:
        """从 settings 读取 Cookie"""
        if self._settings:
            return self._settings.get("wxwork_cookie", "")
        return ""

    def has_cookie(self) -> bool:
        return bool(self._get_cookie())

    # ------------------------------------------------------------------ #
    #  内容提取
    # ------------------------------------------------------------------ #

    def _is_login_page(self, resp) -> bool:
        url = resp.url.lower()
        text_head = resp.text[:3000].lower()
        return (
            "login" in url or "sso" in url
            or "用户未登录" in resp.text[:1000]
            or ("请登录" in text_head and "企业微信" in text_head)
        )

    def _extract_title(self, html: str) -> str:
        patterns = [
            r'<title>(.*?)</title>',
            r'"doc_name"\s*:\s*"([^"]+)"',
            r'data-title="([^"]+)"',
            r'property="og:title"\s+content="([^"]+)"',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE | re.DOTALL)
            if m:
                title = m.group(1).strip()
                # 去掉 " - 企业微信文档" 等后缀
                title = re.sub(r'\s*[-|—]\s*(企业微信|腾讯文档|WeCom|飞书).*$', '', title)
                if title and len(title) < 200:
                    return title
        return ""

    def _extract_text(self, html: str, url: str) -> str:
        """从 HTML 提取纯文本，针对不同平台做优化"""
        # 移除 script/style
        html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        # 段落换行
        html = re.sub(r'<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', html, flags=re.IGNORECASE)
        # 移除所有标签
        text = re.sub(r'<[^>]+>', ' ', html)
        # 解码 HTML 实体
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        # 清理多余空白
        lines = [line.strip() for line in text.split('\n')]
        lines = [l for l in lines if len(l) > 1]  # 去掉单字符行
        text = '\n'.join(lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text[:8000]  # 限制长度
