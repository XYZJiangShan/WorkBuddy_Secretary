/* ==========================================================================
   DeskSecretary PWA - 核心逻辑
   - 通过 GitHub API 读取 tasks.json (查看任务)
   - 通过 GitHub API 写入 inbox.json (添加任务)
   - 配置（owner/repo/branch/token）保存在 localStorage
   ========================================================================== */

const CFG_KEY = "desksec_pwa_config";
const CACHE_KEY = "desksec_pwa_cache";

// ---------- 配置管理 ----------
function getConfig() {
  try {
    return JSON.parse(localStorage.getItem(CFG_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveConfig(cfg) {
  localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
}

function isConfigured() {
  const c = getConfig();
  return c.owner && c.repo;
}

// ---------- GitHub API ----------
function ghHeaders(token) {
  const h = {
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

/**
 * 读取仓库中的文件，返回 {content, sha}（content 已 decode 为字符串）。
 * 公开仓库无需 token，私有仓库需要 token。
 */
async function ghGetFile(path) {
  const cfg = getConfig();
  const branch = cfg.branch || "main";
  const url = `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${path}?ref=${branch}`;
  const res = await fetch(url, { headers: ghHeaders(cfg.token) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub API ${res.status}: ${await res.text()}`);
  const data = await res.json();
  // GitHub 返回的 content 是 base64 编码的，可能含换行
  const b64 = (data.content || "").replace(/\n/g, "");
  // 处理 UTF-8（atob 直接出来是 latin1）
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const content = new TextDecoder("utf-8").decode(bytes);
  return { content, sha: data.sha };
}

/**
 * 写入或更新仓库文件。需要 token（具备 repo 权限）。
 */
async function ghPutFile(path, content, sha, message) {
  const cfg = getConfig();
  if (!cfg.token) throw new Error("需要在配置中填写 GitHub Token 才能写入");
  const branch = cfg.branch || "main";
  const url = `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${path}`;
  // UTF-8 → base64
  const bytes = new TextEncoder().encode(content);
  const b64 = btoa(String.fromCharCode.apply(null, bytes));
  const body = {
    message: message || `pwa: update ${path}`,
    content: b64,
    branch,
  };
  if (sha) body.sha = sha;
  const res = await fetch(url, {
    method: "PUT",
    headers: { ...ghHeaders(cfg.token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`写入失败 ${res.status}: ${err}`);
  }
  return await res.json();
}

// ---------- 数据加载与渲染 ----------
async function loadTasks(showToastOnError = true) {
  if (!isConfigured()) {
    showEmptyState("点右上角 ⚙ 配置 GitHub 仓库后即可同步");
    return;
  }
  try {
    setSyncInfo("同步中...");
    const file = await ghGetFile("tasks.json");
    if (!file) {
      showEmptyState("远端还没有 tasks.json，等电脑端首次同步...");
      setSyncInfo("远端无数据");
      return;
    }
    const data = JSON.parse(file.content);
    localStorage.setItem(CACHE_KEY, file.content);
    renderTasks(data);
    const time = data.exported_at
      ? new Date(data.exported_at).toLocaleString("zh-CN", {
          month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
        })
      : "刚刚";
    setSyncInfo(`已同步 · ${time}`);
  } catch (e) {
    console.error("loadTasks failed", e);
    // 失败时尝试用本地缓存
    const cache = localStorage.getItem(CACHE_KEY);
    if (cache) {
      try {
        renderTasks(JSON.parse(cache));
        setSyncInfo("离线缓存数据");
      } catch {}
    }
    if (showToastOnError) toast(`加载失败: ${e.message}`);
  }
}

function renderTasks(data) {
  const list = document.getElementById("task-list");
  const stats = data.stats || { total: 0, done: 0, undone: 0 };
  document.getElementById("stat-total").textContent = stats.total;
  document.getElementById("stat-done").textContent = stats.done;
  document.getElementById("stat-undone").textContent = stats.undone;

  const tasks = data.today || [];
  if (tasks.length === 0) {
    showEmptyState("今日暂无任务");
    return;
  }
  list.innerHTML = tasks.map(t => renderTaskItem(t)).join("");
}

function renderTaskItem(t) {
  const priorityLabel = { high: "高", medium: "中", low: "低" }[t.priority] || "中";
  const checkmark = t.done ? "✓" : "";
  return `
    <div class="task-item ${t.done ? "done" : ""}">
      <div class="task-checkbox">${checkmark}</div>
      <div class="task-body">
        <div class="task-title">${escapeHtml(t.title)}</div>
        <div class="task-meta">
          <span class="priority-tag ${t.priority}">${priorityLabel}</span>
          ${t.due_time ? `<span>⏰ ${escapeHtml(t.due_time)}</span>` : ""}
        </div>
      </div>
    </div>
  `;
}

function showEmptyState(text) {
  const list = document.getElementById("task-list");
  list.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">📋</div>
      <div class="empty-text">${escapeHtml(text)}</div>
    </div>
  `;
}

function setSyncInfo(text) {
  document.getElementById("sync-info").textContent = text;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- 添加任务（写入 inbox.json） ----------
async function addTask(title, priority) {
  if (!isConfigured()) {
    toast("请先配置 GitHub 仓库");
    return false;
  }
  if (!getConfig().token) {
    toast("请在配置中填写 GitHub Token");
    return false;
  }
  try {
    setSyncInfo("提交中...");
    // 先读取现有 inbox（可能不存在）
    let items = [];
    let sha = null;
    const existing = await ghGetFile("inbox.json");
    if (existing) {
      sha = existing.sha;
      try {
        items = JSON.parse(existing.content) || [];
        if (!Array.isArray(items)) items = [];
      } catch {
        items = [];
      }
    }
    // 追加新任务
    items.push({
      client_id: cryptoRandomId(),
      title: title.trim(),
      priority,
      created_at: new Date().toISOString().slice(0, 19).replace("T", " "),
      source: "pwa",
    });
    const json = JSON.stringify(items, null, 2);
    await ghPutFile("inbox.json", json, sha, `pwa: add task "${title.slice(0, 30)}"`);
    toast("已提交，电脑端下次同步会拉走");
    setSyncInfo("已提交");
    return true;
  } catch (e) {
    console.error("addTask failed", e);
    toast(`提交失败: ${e.message}`);
    return false;
  }
}

function cryptoRandomId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "id-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
}

// ---------- Toast ----------
let toastTimer = null;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.style.display = "none";
  }, 2500);
}

// ---------- 弹窗交互 ----------
function openConfigModal() {
  const c = getConfig();
  document.getElementById("cfg-owner").value = c.owner || "";
  document.getElementById("cfg-repo").value = c.repo || "";
  document.getElementById("cfg-branch").value = c.branch || "main";
  document.getElementById("cfg-token").value = c.token || "";
  document.getElementById("modal-config").style.display = "flex";
}

function closeConfigModal() {
  document.getElementById("modal-config").style.display = "none";
}

function openAddModal() {
  if (!isConfigured() || !getConfig().token) {
    toast("请先配置 GitHub 仓库 + Token");
    openConfigModal();
    return;
  }
  document.getElementById("input-title").value = "";
  document.getElementById("input-priority").value = "medium";
  document.getElementById("modal-add").style.display = "flex";
  setTimeout(() => document.getElementById("input-title").focus(), 100);
}

function closeAddModal() {
  document.getElementById("modal-add").style.display = "none";
}

// ---------- 初始化 ----------
function init() {
  // 先用本地缓存渲染（秒开）
  const cache = localStorage.getItem(CACHE_KEY);
  if (cache) {
    try { renderTasks(JSON.parse(cache)); } catch {}
  }
  // 异步拉新数据
  loadTasks(false);

  // 按钮绑定
  document.getElementById("btn-sync").addEventListener("click", () => loadTasks(true));
  document.getElementById("btn-config").addEventListener("click", openConfigModal);
  document.getElementById("btn-add").addEventListener("click", openAddModal);

  document.getElementById("btn-save-config").addEventListener("click", () => {
    const cfg = {
      owner: document.getElementById("cfg-owner").value.trim(),
      repo: document.getElementById("cfg-repo").value.trim(),
      branch: document.getElementById("cfg-branch").value.trim() || "main",
      token: document.getElementById("cfg-token").value.trim(),
    };
    if (!cfg.owner || !cfg.repo) {
      toast("用户名和仓库名必填");
      return;
    }
    saveConfig(cfg);
    closeConfigModal();
    toast("配置已保存");
    loadTasks(true);
  });

  document.getElementById("btn-confirm-add").addEventListener("click", async () => {
    const title = document.getElementById("input-title").value.trim();
    if (!title) {
      toast("请输入任务标题");
      return;
    }
    const priority = document.getElementById("input-priority").value;
    const btn = document.getElementById("btn-confirm-add");
    btn.disabled = true;
    btn.textContent = "提交中...";
    const ok = await addTask(title, priority);
    btn.disabled = false;
    btn.textContent = "添加";
    if (ok) closeAddModal();
  });

  // 回车提交
  document.getElementById("input-title").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      document.getElementById("btn-confirm-add").click();
    }
  });

  // 注册 Service Worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(err => {
      console.warn("SW register failed", err);
    });
  }

  // 切回前台时刷新
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadTasks(false);
  });
}

document.addEventListener("DOMContentLoaded", init);
