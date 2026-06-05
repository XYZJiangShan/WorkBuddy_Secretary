"""
single_instance.py - 单实例保护服务

确保桌面小秘书同一时间只有一个实例在运行。
重复启动时，第二个实例会通知已运行的实例"显示窗口"，然后自己退出。

实现：
  - QSharedMemory：跨进程的原子性"已运行"标记（attach 成功 = 已有实例）
  - QLocalServer/QLocalSocket：本地 IPC，第二实例通过它唤起首个实例的窗口

为什么不用 PID 文件：
  PID 文件在程序崩溃后会残留，导致永远启动不了；
  QSharedMemory 随进程退出自动释放（Windows 下），更可靠。
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import QSharedMemory

logger = logging.getLogger(__name__)

# 唯一标识（同一用户下全局唯一即可）
_APP_KEY = "DeskSecretary_SingleInstance_v1"
_SERVER_NAME = "DeskSecretary_IPC_v1"


class SingleInstance(QObject):
    """
    单实例守卫。

    用法：
        guard = SingleInstance()
        if guard.is_already_running():
            guard.notify_existing()   # 通知已有实例显示窗口
            sys.exit(0)               # 自己退出
        guard.start_server()          # 作为首实例，启动 IPC 服务监听
        guard.activate_requested.connect(show_window)

    Signals:
        activate_requested()  收到其他实例的"请显示窗口"请求
    """

    activate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shared = QSharedMemory(_APP_KEY)
        self._server: QLocalServer | None = None
        self._is_primary = False

    # ------------------------------------------------------------------ #

    def is_already_running(self) -> bool:
        """
        检测是否已有实例在运行。

        返回 True  = 已有实例（自己是后来者，应退出）
        返回 False = 没有实例（自己是首实例，应继续启动）
        """
        # 尝试 attach：成功说明共享内存已存在 → 已有实例
        if self._shared.attach():
            # 立即 detach，避免后来者也持有引用
            self._shared.detach()
            return True

        # attach 失败 → 尝试 create：成功说明自己是首实例
        if self._shared.create(1):
            self._is_primary = True
            return False

        # create 也失败：可能是上次异常退出残留的共享内存（仅 Linux/macOS 会残留）
        # Windows 下共享内存随最后一个引用释放而销毁，不会走到这；
        # 为稳健起见，强制 detach 后重试一次
        self._shared.detach()
        if self._shared.create(1):
            self._is_primary = True
            return False

        # 仍失败，保守认为已有实例在运行
        logger.warning("共享内存创建失败，可能已有实例运行")
        return True

    def start_server(self) -> None:
        """作为首实例，启动本地 IPC 服务，监听后来者的唤起请求"""
        # 先移除可能残留的同名服务（上次崩溃遗留）
        QLocalServer.removeServer(_SERVER_NAME)

        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(_SERVER_NAME):
            logger.warning("IPC 服务监听失败: %s", self._server.errorString())
        else:
            logger.info("单实例 IPC 服务已启动")

    def notify_existing(self) -> bool:
        """
        作为后来者，通知已运行的首实例"显示窗口"。
        返回 True 表示通知成功。
        """
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)
        if socket.waitForConnected(800):
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(800)
            socket.disconnectFromServer()
            logger.info("已通知首实例显示窗口")
            return True
        logger.warning("无法连接首实例 IPC 服务: %s", socket.errorString())
        return False

    def _on_new_connection(self) -> None:
        """首实例收到后来者的连接 → 发射 activate 信号"""
        if not self._server:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        # 读取消息（可选），无论内容如何都触发显示
        socket.waitForReadyRead(500)
        try:
            _ = socket.readAll()
        except Exception:
            pass
        socket.disconnectFromServer()
        logger.info("收到唤起请求，显示主窗口")
        self.activate_requested.emit()

    def cleanup(self) -> None:
        """退出时清理（释放共享内存 + 关闭服务）"""
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(_SERVER_NAME)
        if self._shared.isAttached():
            self._shared.detach()
