"""
settings_repository.py - 应用配置读写

基于 settings 表（key-value 结构）封装配置的读写操作。
支持带默认值的 get，以及批量更新，类型转换由调用方负责。
"""

from __future__ import annotations

from data.database import get_conn


# --------------------------------------------------------------------------- #
#  默认配置
# --------------------------------------------------------------------------- #

DEFAULT_SETTINGS: dict[str, str] = {
    # AI 接口配置
    "ai_enabled": "1",               # 1=启用AI功能, 0=纯本地模式
    "ai_api_key": "",
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_model": "deepseek-chat",
    "ai_timeout": "10",              # 秒

    # 提醒配置
    "reminder_interval_minutes": "45",   # 提醒间隔（分钟）
    "reminder_enabled": "1",             # 1=开启, 0=关闭
    "reminder_cache_size": "5",          # 预拉取文案条数

    # UI 配置
    "window_opacity": "0.92",            # 悬浮窗不透明度 0.1~1.0
    "window_x": "-1",                    # -1 表示默认位置
    "window_y": "-1",
    "window_width": "310",               # 窗口宽度
    "window_height": "520",              # 窗口高度
    "window_collapsed": "0",             # 0=展开, 1=折叠
    "theme": "light",                    # light / dark

    # 番茄钟配置
    "pomodoro_focus_minutes": "25",
    "pomodoro_short_break_minutes": "5",
    "pomodoro_long_break_minutes": "15",

    # 全局热键
    "hotkey_toggle_window": "alt+space",
    "hotkey_enabled": "1",
}


# --------------------------------------------------------------------------- #
#  Repository
# --------------------------------------------------------------------------- #

class SettingsRepository:
    """配置读写封装，操作 settings 表"""

    def _ensure_defaults(self) -> None:
        """写入所有缺失的默认值（幂等，已有值不覆盖）"""
        conn = get_conn()
        conn.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            list(DEFAULT_SETTINGS.items()),
        )
        conn.commit()

    # ------------------------------------------------------------------ #
    #  读操作
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: str = "") -> str:
        """读取单个配置项，未找到时返回默认值"""
        conn = get_conn()
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row:
            return row[0]
        # 尝试从内置默认值返回
        return DEFAULT_SETTINGS.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """读取整型配置项"""
        val = self.get(key, str(default))
        try:
            return int(val)
        except ValueError:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """读取浮点型配置项"""
        val = self.get(key, str(default))
        try:
            return float(val)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔配置项（存储为 '1'/'0'）"""
        val = self.get(key, "1" if default else "0")
        return val.strip() == "1"

    def get_all(self) -> dict[str, str]:
        """读取所有配置项，返回字典"""
        conn = get_conn()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        result = dict(DEFAULT_SETTINGS)  # 先填默认值
        result.update({r[0]: r[1] for r in rows})
        return result

    # ------------------------------------------------------------------ #
    #  写操作
    # ------------------------------------------------------------------ #

    def set(self, key: str, value: str) -> None:
        """写入单个配置项（不存在则插入，存在则更新）"""
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        conn.commit()

    def set_many(self, mapping: dict[str, str]) -> None:
        """批量写入配置项"""
        conn = get_conn()
        conn.executemany(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            [(k, str(v)) for k, v in mapping.items()],
        )
        conn.commit()

    def delete(self, key: str) -> None:
        """删除配置项（恢复为内置默认值）"""
        conn = get_conn()
        conn.execute("DELETE FROM settings WHERE key=?", (key,))
        conn.commit()

    def reset_to_defaults(self) -> None:
        """清空所有配置，重新写入默认值"""
        conn = get_conn()
        conn.execute("DELETE FROM settings")
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            list(DEFAULT_SETTINGS.items()),
        )
        conn.commit()

    def initialize(self) -> None:
        """程序启动时调用：确保所有默认配置已写入"""
        self._ensure_defaults()
