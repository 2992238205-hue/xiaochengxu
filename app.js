const STORAGE_KEY = "english_reader_mvp_v2";
const PASS_RATE = 0.8;
const APP_CONFIG = window.APP_CONFIG || {};
const API_BASE = String(APP_CONFIG.apiBaseUrl || "").replace(/\/$/, "");
const SERVER_MODE = API_BASE.length > 0;
const USER_CAN_UPLOAD = SERVER_MODE ? Boolean(APP_CONFIG.userCanUpload) : true;
const TRANSLATION_CACHE_LIMIT = 1800;
const QUIZ_DRAW_COUNT = 30;
const TAP_ZONE_RATIO = 0.32;

const fallbackDemoBook = {
  id: "fallback-deep-focus",
  title: "Deep Focus Journey (Fallback)",
  description: "内置示例，用于离线或加载失败兜底",
  wordGoal: 3500,
  chapters: [
    {
      title: "Chapter 1: Focus First",
      english:
        "Lin made a small promise to himself. He would protect one quiet hour each evening for reading and vocabulary training. No messages, no games, and no random videos were allowed in that hour.\n\nAt first, the rule felt strict. But after a few days, Lin noticed that his memory became sharper, and reading no longer felt heavy.\n\nHe wrote one line in his notebook: Deep thinking starts from disciplined attention.",
      chinese:
        "林给自己一个小承诺：每天晚上保护一小时专注阅读和词汇训练。那一小时里，不看消息，不玩游戏，不刷短视频。\n\n开始时规则很严格，但几天后，他发现记忆变清晰，阅读也不再吃力。\n\n他在笔记本写下一句话：深度思考始于有纪律的注意力。",
      targetWords: [
        { word: "promise", translation: "承诺" },
        { word: "protect", translation: "保护" },
        { word: "quiet", translation: "安静的" },
        { word: "strict", translation: "严格的" },
        { word: "memory", translation: "记忆" },
        { word: "disciplined", translation: "有纪律的" }
      ]
    }
  ]
};

const baseDictionary = {
  focus: "专注",
  growth: "成长",
  challenge: "挑战",
  memory: "记忆",
  logic: "逻辑",
  method: "方法",
  chapter: "章节",
  novel: "小说",
  effort: "努力",
  achieve: "实现",
  improve: "提升",
  habit: "习惯",
  confidence: "自信",
  insight: "洞察",
  system: "系统",
  skill: "技能",
  practice: "练习",
  result: "结果",
  progress: "进步",
  strategy: "策略",
  routine: "日常",
  clear: "清晰的",
  attention: "注意力",
  reflect: "反思",
  mastery: "精通"
};

const state = {
  profile: {
    age: "",
    stage: "初中",
    track: ""
  },
  books: [],
  progressByBook: {},
  settings: {
    fontSize: 20,
    lineHeight: 1.7,
    showChinese: false,
    readerTheme: "paper",
    nightMode: false
  },
  commentsByAnchor: {},
  activeBookId: null,
  activeChapterIndex: 0,
  activePageIndex: 0,
  cachedPagesKey: "",
  pages: [],
  quizQuestions: [],
  translationCache: {},
  activeLookupToken: "",
  readerUiVisible: false,
  commentContext: null,
  pendingChapterAdvance: false,
  auth: {
    authenticated: false,
    user: null
  },
  quota: {
    monthKey: "",
    used: 0,
    limit: 20,
    remaining: 20
  },
  historyItems: [],
  bookManageMode: false,
  selectedPersonalBookIds: {},
  historyLastReportAt: 0,
  historyLastReportKey: ""
};

const elements = {
  tabs: document.querySelectorAll("[data-view]"),
  views: {
    shelf: document.getElementById("shelf-view"),
    reader: document.getElementById("reader-view"),
    profile: document.getElementById("profile-view")
  },
  importCard: document.getElementById("import-card"),
  readerStage: document.getElementById("reader-stage"),
  readerBack: document.getElementById("reader-back"),
  bookshelfList: document.getElementById("bookshelf-list"),
  bookImport: document.getElementById("book-import"),
  readerBookTitle: document.getElementById("reader-book-title"),
  readerChapterTitle: document.getElementById("reader-chapter-title"),
  chapterSelect: document.getElementById("chapter-select"),
  readingPanel: document.getElementById("reading-panel"),
  pageIndicator: document.getElementById("page-indicator"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  prevChapter: document.getElementById("prev-chapter"),
  nextChapter: document.getElementById("next-chapter"),
  fontSize: document.getElementById("font-size"),
  lineHeight: document.getElementById("line-height"),
  readerTheme: document.getElementById("reader-theme"),
  nightMode: document.getElementById("night-mode"),
  showChinese: document.getElementById("show-chinese"),
  gateStatus: document.getElementById("gate-status"),
  startQuiz: document.getElementById("start-quiz"),
  translationCard: document.getElementById("translation-card"),
  readerBottomSheet: document.getElementById("reader-bottom-sheet"),
  chinesePanel: document.getElementById("chinese-panel"),
  translationWord: document.getElementById("translation-word"),
  translationMeaning: document.getElementById("translation-meaning"),
  speakWord: document.getElementById("speak-word"),
  profileForm: document.getElementById("profile-form"),
  profileAge: document.getElementById("profile-age"),
  profileStage: document.getElementById("profile-stage"),
  profileTrack: document.getElementById("profile-track"),
  progressLabel: document.getElementById("progress-label"),
  progressFill: document.getElementById("progress-fill"),
  quizDialog: document.getElementById("quiz-dialog"),
  quizForm: document.getElementById("quiz-form"),
  quizQuestions: document.getElementById("quiz-questions"),
  quizSubtitle: document.getElementById("quiz-subtitle"),
  cancelQuiz: document.getElementById("cancel-quiz"),
  focusModeButton: document.getElementById("focus-mode-button"),
  focusDialog: document.getElementById("focus-dialog"),
  closeFocusDialog: document.getElementById("close-focus-dialog"),
  commentInputDialog: document.getElementById("comment-input-dialog"),
  commentInputForm: document.getElementById("comment-input-form"),
  commentAnchorPreview: document.getElementById("comment-anchor-preview"),
  commentText: document.getElementById("comment-text"),
  cancelCommentInput: document.getElementById("cancel-comment-input"),
  commentListDialog: document.getElementById("comment-list-dialog"),
  commentListTitle: document.getElementById("comment-list-title"),
  commentListAnchor: document.getElementById("comment-list-anchor"),
  commentListBody: document.getElementById("comment-list-body"),
  closeCommentList: document.getElementById("close-comment-list"),
  addCommentFromList: document.getElementById("add-comment-from-list")
  ,
  authMini: document.getElementById("auth-mini"),
  authStatusText: document.getElementById("auth-status-text"),
  authPhone: document.getElementById("auth-phone"),
  authOtp: document.getElementById("auth-otp"),
  sendOtp: document.getElementById("send-otp"),
  verifyOtp: document.getElementById("verify-otp"),
  logoutButton: document.getElementById("logout-button"),
  quotaLabel: document.getElementById("quota-label"),
  quotaFill: document.getElementById("quota-fill"),
  readingHistoryList: document.getElementById("reading-history-list"),
  openGenerator: document.getElementById("open-generator"),
  refreshShelf: document.getElementById("refresh-shelf"),
  toggleManageBooks: document.getElementById("toggle-manage-books"),
  batchDeleteBooks: document.getElementById("batch-delete-books"),
  personalBookActions: document.getElementById("personal-book-actions"),
  bottomNav: document.getElementById("bottom-nav"),
  bottomNavButtons: document.querySelectorAll("[data-bottom-nav]")
};

let speakingWord = "";
let wakeLock = null;
let longPressTimer = null;
let longPressTriggered = false;
let layoutRaf = 0;
const translationRequestCache = new Map();
let pointerStartX = 0;
let pointerStartY = 0;
let pointerMoved = false;
let suppressTapUntil = 0;
let readingScrollRaf = 0;

async function apiFetchJSON(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || (data && data.ok === false)) {
    const message = (data && (data.error || data.message)) || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data;
}

async function refreshAuthMe() {
  if (!SERVER_MODE) {
    state.auth.authenticated = false;
    state.auth.user = null;
    return;
  }
  try {
    const data = await apiFetchJSON(`${API_BASE}/auth/me`, { cache: "no-store" });
    state.auth.authenticated = Boolean(data.authenticated);
    state.auth.user = data.user || null;
  } catch (_err) {
    state.auth.authenticated = false;
    state.auth.user = null;
  }
}

function hasLocalReaderData() {
  const hasProfile = Boolean(state.profile && (state.profile.age || state.profile.track));
  const hasProgress = Boolean(state.progressByBook && Object.keys(state.progressByBook).length > 0);
  const hasComments = Boolean(state.commentsByAnchor && Object.keys(state.commentsByAnchor).length > 0);
  return hasProfile || hasProgress || hasComments;
}

async function loadUserStateFromServer() {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  try {
    const data = await apiFetchJSON(`${API_BASE}/user/state`, { cache: "no-store" });
    const remoteState = data.state || {};
    const remoteEmpty =
      (!remoteState.profile || Object.keys(remoteState.profile).length === 0) &&
      (!remoteState.progressByBook || Object.keys(remoteState.progressByBook).length === 0) &&
      (!remoteState.settings || Object.keys(remoteState.settings).length === 0) &&
      (!remoteState.commentsByAnchor || Object.keys(remoteState.commentsByAnchor).length === 0);
    if (remoteEmpty && hasLocalReaderData()) {
      const shouldImport = window.confirm("检测到本地学习数据，是否迁移到当前账号？");
      if (shouldImport) {
        await apiFetchJSON(`${API_BASE}/user/state/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            profile: state.profile,
            progressByBook: state.progressByBook,
            settings: state.settings,
            commentsByAnchor: state.commentsByAnchor
          })
        });
      }
    } else {
      if (remoteState.profile && typeof remoteState.profile === "object") {
        state.profile = remoteState.profile;
      }
      if (remoteState.progressByBook && typeof remoteState.progressByBook === "object") {
        state.progressByBook = remoteState.progressByBook;
      }
      if (remoteState.settings && typeof remoteState.settings === "object") {
        state.settings = { ...state.settings, ...remoteState.settings };
      }
      if (remoteState.commentsByAnchor && typeof remoteState.commentsByAnchor === "object") {
        state.commentsByAnchor = remoteState.commentsByAnchor;
      }
    }
  } catch (_err) {
    // ignore
  }
}

let syncStateTimer = 0;
function scheduleServerStateSync() {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  if (syncStateTimer) {
    clearTimeout(syncStateTimer);
  }
  syncStateTimer = setTimeout(async () => {
    syncStateTimer = 0;
    try {
      await apiFetchJSON(`${API_BASE}/user/state`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile: state.profile,
          progressByBook: state.progressByBook,
          settings: state.settings,
          commentsByAnchor: state.commentsByAnchor
        })
      });
    } catch (_err) {
      // ignore
    }
  }, 800);
}

async function refreshQuota() {
  if (!SERVER_MODE || !state.auth.authenticated) {
    state.quota = { monthKey: "", used: 0, limit: 20, remaining: 20 };
    return;
  }
  try {
    const data = await apiFetchJSON(`${API_BASE}/user/quota`, { cache: "no-store" });
    state.quota = {
      monthKey: String(data.monthKey || ""),
      used: Number(data.used || 0),
      limit: Number(data.limit || 20),
      remaining: Number(data.remaining || 0)
    };
  } catch (_err) {
    state.quota = { monthKey: "", used: 0, limit: 20, remaining: 20 };
  }
}

async function refreshReadingHistory() {
  if (!SERVER_MODE || !state.auth.authenticated) {
    state.historyItems = [];
    return;
  }
  try {
    const data = await apiFetchJSON(`${API_BASE}/user/reading-history?limit=200`, { cache: "no-store" });
    state.historyItems = Array.isArray(data.items) ? data.items : [];
  } catch (_err) {
    state.historyItems = [];
  }
}

async function init() {
  hydrateState();
  bindEvents();

  if (!USER_CAN_UPLOAD && elements.importCard) {
    elements.importCard.style.display = "none";
  }

  await refreshAuthMe();

  let loadedFromServer = false;
  if (SERVER_MODE) {
    loadedFromServer = await loadBooksFromServer();
    if (state.auth.authenticated) {
      await loadUserStateFromServer();
      await refreshQuota();
      await refreshReadingHistory();
    }
  }
  if (!loadedFromServer) {
    await ensureDemoBook();
  }

  if (!state.activeBookId && state.books.length > 0) {
    state.activeBookId = state.books[0].id;
    ensureProgress(state.activeBookId);
  }

  renderShelf();
  renderProfile();
  renderReader();
  renderAuthPanel();
  const hashView = viewFromHash();
  if (hashView) {
    switchView(hashView);
  }
  scheduleReaderLayoutMetrics();
  saveState();
}

function bindEvents() {
  elements.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.view;
      if (target === "generator") {
        window.location.href = "/generator";
        return;
      }
      switchView(target);
    });
  });
  elements.bottomNavButtons.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.bottomNav;
      if (target === "generator") {
        window.location.href = "/generator";
        return;
      }
      switchView(target);
    });
  });

  elements.readerBack.addEventListener("click", () => switchView("shelf"));
  elements.bookImport.addEventListener("change", importBookFile);
  elements.chapterSelect.addEventListener("change", onChapterChange);
  elements.prevPage.addEventListener("click", () => turnPage(-1));
  elements.nextPage.addEventListener("click", () => turnPage(1));
  elements.prevChapter.addEventListener("click", () => navigateChapter(-1));
  elements.nextChapter.addEventListener("click", () => navigateChapter(1));
  elements.fontSize.addEventListener("input", onReaderStyleChange);
  elements.lineHeight.addEventListener("input", onReaderStyleChange);
  elements.readerTheme.addEventListener("change", onReaderStyleChange);
  elements.nightMode.addEventListener("change", onReaderStyleChange);
  elements.showChinese.addEventListener("change", onReaderStyleChange);
  elements.startQuiz.addEventListener("click", beginQuiz);
  elements.speakWord.addEventListener("click", () => speakWord(speakingWord));

  elements.readingPanel.addEventListener("click", onReadingPanelClick);
  elements.readingPanel.addEventListener("scroll", onReadingPanelScroll, { passive: true });
  elements.readingPanel.addEventListener("pointerdown", onReadingPanelPointerDown);
  elements.readingPanel.addEventListener("pointermove", onReadingPanelPointerMove);
  elements.readingPanel.addEventListener("pointerup", onReadingPanelPointerUp);
  elements.readingPanel.addEventListener("pointerleave", onReadingPanelPointerUp);
  elements.readingPanel.addEventListener("pointercancel", onReadingPanelPointerUp);
  elements.readerStage.addEventListener("click", onReaderStageClick);

  elements.profileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    state.profile.age = elements.profileAge.value.trim();
    state.profile.stage = elements.profileStage.value;
    state.profile.track = elements.profileTrack.value.trim();
    saveState();
    renderProfile();
    alert("学习信息已保存");
  });

  elements.quizForm.addEventListener("submit", submitQuiz);
  elements.cancelQuiz.addEventListener("click", () => {
    state.pendingChapterAdvance = false;
    elements.quizDialog.close();
  });

  elements.focusModeButton.addEventListener("click", async () => {
    elements.focusDialog.showModal();
    await enterFocusMode();
  });
  elements.closeFocusDialog.addEventListener("click", () => elements.focusDialog.close());

  elements.commentInputForm.addEventListener("submit", submitCommentInput);
  elements.cancelCommentInput.addEventListener("click", () => elements.commentInputDialog.close());
  elements.closeCommentList.addEventListener("click", () => elements.commentListDialog.close());
  elements.addCommentFromList.addEventListener("click", () => {
    elements.commentListDialog.close();
    if (state.commentContext) {
      openCommentInput(state.commentContext.anchorId, state.commentContext.preview, state.commentContext.pageIndex);
    }
  });

  elements.sendOtp.addEventListener("click", onSendOtp);
  elements.verifyOtp.addEventListener("click", onVerifyOtp);
  elements.logoutButton.addEventListener("click", onLogout);
  elements.refreshShelf?.addEventListener("click", () => {
    if (!SERVER_MODE) {
      return;
    }
    void refreshShelfFromServer();
  });
  elements.openGenerator?.addEventListener("click", () => {
    if (!state.auth.authenticated) {
      alert("请先登录后使用生成器。");
      switchView("profile");
      return;
    }
    window.location.href = "/generator";
  });
  elements.toggleManageBooks?.addEventListener("click", () => {
    state.bookManageMode = !state.bookManageMode;
    state.selectedPersonalBookIds = {};
    renderShelf();
    renderAuthPanel();
  });
  elements.batchDeleteBooks?.addEventListener("click", onBatchDeleteBooks);

  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") {
      turnPage(1);
    }
    if (event.key === "ArrowLeft") {
      turnPage(-1);
    }
  });

  window.addEventListener("resize", scheduleReaderLayoutMetrics);
  window.addEventListener("orientationchange", scheduleReaderLayoutMetrics);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      void reportReadingHistory();
      return;
    }
    if (document.visibilityState === "visible" && SERVER_MODE && isViewActive("shelf")) {
      void refreshShelfFromServer();
    }
  });
  window.addEventListener("focus", () => {
    if (SERVER_MODE && isViewActive("shelf")) {
      void refreshShelfFromServer();
    }
  });
  window.addEventListener("storage", (event) => {
    if (!SERVER_MODE) {
      return;
    }
    if (event.key === "reader_shelf_updated_at") {
      void refreshShelfFromServer();
    }
  });
  window.addEventListener("beforeunload", () => {
    if (state.auth.authenticated) {
      const payload = buildReadingHistoryPayload();
      if (!payload || !navigator.sendBeacon) {
        return;
      }
      const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
      navigator.sendBeacon(`${API_BASE}/user/reading-history`, blob);
    }
  });
}

function hydrateState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return;
  }

  try {
    const parsed = JSON.parse(raw);
    state.profile = parsed.profile || state.profile;
    state.books = Array.isArray(parsed.books) ? parsed.books.map((book) => normalizeBook(book)) : [];
    state.progressByBook = parsed.progressByBook || {};
    state.settings = {
      ...state.settings,
      ...(parsed.settings || {})
    };
    if (!["paper", "green"].includes(String(state.settings.readerTheme || ""))) {
      state.settings.readerTheme = "paper";
    }
    state.settings.nightMode = Boolean(state.settings.nightMode);
    state.commentsByAnchor = parsed.commentsByAnchor || {};
    state.activeBookId = parsed.activeBookId || null;
    state.translationCache = parsed.translationCache || {};
  } catch (error) {
    console.warn("状态恢复失败，已忽略旧数据:", error);
  }
}

function trimTranslationCache() {
  const entries = Object.entries(state.translationCache || {});
  if (entries.length <= TRANSLATION_CACHE_LIMIT) {
    return;
  }
  state.translationCache = Object.fromEntries(entries.slice(entries.length - TRANSLATION_CACHE_LIMIT));
}

function saveState() {
  trimTranslationCache();
  const snapshot = {
    profile: state.profile,
    books: state.books,
    progressByBook: state.progressByBook,
    settings: state.settings,
    commentsByAnchor: state.commentsByAnchor,
    activeBookId: state.activeBookId,
    translationCache: state.translationCache
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  scheduleServerStateSync();
}

function renderAuthPanel() {
  const loggedIn = Boolean(state.auth.authenticated);
  const phoneMasked = state.auth.user?.phoneMasked || "";
  elements.authMini.textContent = loggedIn ? `已登录 ${phoneMasked}` : "未登录";
  elements.authStatusText.textContent = loggedIn ? `当前账号：${phoneMasked}` : "未登录";
  elements.bottomNav.classList.toggle("hidden", !loggedIn);
  elements.personalBookActions.classList.toggle("hidden", !loggedIn);
  if (elements.toggleManageBooks) {
    elements.toggleManageBooks.textContent = state.bookManageMode ? "退出管理" : "管理个人书架";
  }
  if (elements.batchDeleteBooks) {
    const selectedCount = Object.values(state.selectedPersonalBookIds).filter(Boolean).length;
    elements.batchDeleteBooks.textContent = selectedCount > 0 ? `批量删除(${selectedCount})` : "批量删除";
    elements.batchDeleteBooks.disabled = selectedCount === 0;
  }

  const used = Number(state.quota.used || 0);
  const limit = Math.max(1, Number(state.quota.limit || 20));
  const ratio = Math.min(100, Math.round((used / limit) * 100));
  elements.quotaLabel.textContent = loggedIn
    ? `${state.quota.monthKey || "-"}：${used}/${limit}，剩余 ${Math.max(0, limit - used)}`
    : "未登录";
  elements.quotaFill.style.width = `${ratio}%`;
}

function renderReadingHistoryPanel() {
  if (!state.auth.authenticated) {
    elements.readingHistoryList.innerHTML = "<p>登录后可查看阅读历史</p>";
    return;
  }
  if (!Array.isArray(state.historyItems) || state.historyItems.length === 0) {
    elements.readingHistoryList.innerHTML = "<p>暂无历史记录</p>";
    return;
  }
  elements.readingHistoryList.innerHTML = "";
  state.historyItems.forEach((item) => {
    const node = document.createElement("article");
    node.className = "book-item";
    node.innerHTML = `
      <h3>${escapeHtml(item.bookTitle || item.bookId || "未命名")}</h3>
      <p>${escapeHtml(item.chapterTitle || `Chapter ${Number(item.chapterIndex || 0) + 1}`)}</p>
      <p>页码：${Number(item.pageIndex || 0) + 1}</p>
      <p>${escapeHtml(item.viewedAt || "")}</p>
      <button class="primary-button" data-jump-history="${escapeAttr(item.id)}">继续阅读</button>
    `;
    elements.readingHistoryList.appendChild(node);
  });
  elements.readingHistoryList.querySelectorAll("button[data-jump-history]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.jumpHistory;
      const item = state.historyItems.find((entry) => entry.id === id);
      if (!item) {
        return;
      }
      if (jumpToHistory(item)) {
        switchView("reader");
      } else {
        alert("该记录对应的书籍已不存在。");
      }
    });
  });
}

async function onSendOtp() {
  if (!SERVER_MODE) {
    alert("当前不是服务端模式，无法短信登录。");
    return;
  }
  const phone = elements.authPhone.value.trim();
  if (!phone) {
    alert("请先输入手机号。");
    return;
  }
  try {
    const data = await apiFetchJSON(`${API_BASE}/auth/otp/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone })
    });
    alert(`验证码已发送，请在 ${data.cooldownSeconds || 60} 秒后重发。`);
  } catch (err) {
    alert(`发送失败：${err.message}`);
  }
}

async function onVerifyOtp() {
  if (!SERVER_MODE) {
    return;
  }
  const phone = elements.authPhone.value.trim();
  const code = elements.authOtp.value.trim();
  if (!phone || !code) {
    alert("请输入手机号与验证码。");
    return;
  }
  try {
    await apiFetchJSON(`${API_BASE}/auth/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, code })
    });
    await refreshAuthMe();
    await loadBooksFromServer();
    await loadUserStateFromServer();
    await refreshQuota();
    await refreshReadingHistory();
    renderShelf();
    renderReader();
    renderProfile();
    renderAuthPanel();
    saveState();
    alert("登录成功");
  } catch (err) {
    alert(`登录失败：${err.message}`);
  }
}

async function onLogout() {
  if (!SERVER_MODE) {
    return;
  }
  try {
    await apiFetchJSON(`${API_BASE}/auth/logout`, { method: "POST" });
  } catch (_err) {
    // ignore
  }
  state.auth.authenticated = false;
  state.auth.user = null;
  state.quota = { monthKey: "", used: 0, limit: 20, remaining: 20 };
  state.historyItems = [];
  state.bookManageMode = false;
  state.selectedPersonalBookIds = {};
  await loadBooksFromServer();
  renderShelf();
  renderReader();
  renderProfile();
  renderAuthPanel();
}

function jumpToHistory(item) {
  const bookId = String(item.bookId || "");
  const chapterIndex = Number(item.chapterIndex || 0);
  const pageIndex = Number(item.pageIndex || 0);
  const book = state.books.find((b) => b.id === bookId);
  if (!book) {
    return false;
  }
  state.activeBookId = bookId;
  ensureProgress(bookId);
  unlockChapterAtLeast(chapterIndex);
  state.activeChapterIndex = Math.max(0, Math.min(chapterIndex, book.chapters.length - 1));
  state.activePageIndex = Math.max(0, pageIndex);
  state.cachedPagesKey = "";
  renderReader();
  if (state.pages.length > 0) {
    state.activePageIndex = Math.max(0, Math.min(state.activePageIndex, state.pages.length - 1));
    paintCurrentPage();
  }
  saveState();
  return true;
}

function decodeHtmlEntities(input) {
  if (input === null || input === undefined) {
    return "";
  }
  let text = String(input);
  const parser = new DOMParser();
  for (let i = 0; i < 3; i += 1) {
    const doc = parser.parseFromString(`<!doctype html><body>${text}`, "text/html");
    const decoded = doc.body.textContent || "";
    if (decoded === text) {
      break;
    }
    text = decoded;
  }
  return text;
}

async function ensureDemoBook() {
  if (state.books.length > 0) {
    return;
  }
  try {
    const response = await fetch("./content/demo-book.json");
    const book = await response.json();
    upsertBook(book);
  } catch (error) {
    upsertBook(fallbackDemoBook);
    console.warn("加载外部示例失败，已启用内置示例:", error);
  }
}

async function loadBooksFromServer() {
  try {
    const endpoints = state.auth.authenticated
      ? [`${API_BASE}/user/books`, `${API_BASE}/public/books`]
      : [`${API_BASE}/public/books`];
    let incomingBooks = [];
    let loaded = false;
    for (const endpoint of endpoints) {
      const response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) {
        continue;
      }
      const data = await response.json();
      incomingBooks = Array.isArray(data.books) ? data.books : [];
      loaded = true;
      break;
    }
    if (!loaded) {
      return false;
    }
    const normalizedBooks = [];
    incomingBooks.forEach((rawBook) => {
      try {
        normalizedBooks.push(normalizeBook(rawBook));
      } catch (error) {
        console.warn("跳过异常书籍：", rawBook?.id || rawBook?.title || "unknown", error?.message || error);
      }
    });
    state.books = normalizedBooks;
    if (!state.activeBookId || !state.books.find((book) => book.id === state.activeBookId)) {
      state.activeBookId = state.books.length > 0 ? state.books[0].id : null;
    }
    saveState();
    return true;
  } catch (_error) {
    return false;
  }
}

async function refreshShelfFromServer() {
  const loaded = await loadBooksFromServer();
  if (!loaded) {
    return;
  }
  renderShelf();
  renderReader();
}

function upsertBook(rawBook) {
  const book = normalizeBook(rawBook);
  const foundIndex = state.books.findIndex((item) => item.id === book.id);
  if (foundIndex === -1) {
    state.books.push(book);
  } else {
    state.books[foundIndex] = book;
  }
  ensureProgress(book.id);
  state.activeBookId = book.id;
  saveState();
}

function normalizeBook(rawBook) {
  const chapters = Array.isArray(rawBook.chapters) ? rawBook.chapters : [];
  const safeChapters = chapters
    .map((chapter, index) => {
      const targetWords = Array.isArray(chapter.targetWords)
        ? chapter.targetWords
            .map((entry) => {
              if (!entry || !entry.word) {
                return null;
              }
              return {
                word: String(entry.word).trim(),
                translation: String(entry.translation || "").trim() || "未提供翻译"
              };
            })
            .filter(Boolean)
        : [];

      // Normalize any LLM / imported content:
      // - decode HTML entities (&quot; etc)
      // - strip Markdown emphasis (**bold**) so the reader always shows clean text
      const english = sanitizeBookText(chapter.english || chapter.content || "");
      const chinese = sanitizeBookText(chapter.chinese || "");
      const displayText = english || chinese;

      return {
        title: decodeHtmlEntities(String(chapter.title || `Chapter ${index + 1}`)).trim(),
        english: displayText,
        chinese,
        targetWords
      };
    })
    .filter((chapter) => chapter.english.length > 0 || chapter.chinese.length > 0);

  if (safeChapters.length === 0) {
    throw new Error("小说章节为空，至少需要一章正文。");
  }

  return {
    id: String(rawBook.id || `book-${Date.now()}`),
    title: decodeHtmlEntities(String(rawBook.title || "未命名小说")).trim(),
    description: decodeHtmlEntities(String(rawBook.description || "已导入小说")).trim(),
    wordGoal: Number(rawBook.wordGoal || 3500),
    coverUrl: decodeHtmlEntities(String(rawBook.coverUrl || "")).trim(),
    category: decodeHtmlEntities(String(rawBook.category || "")).trim(),
    sortOrder: Number(rawBook.sortOrder || 0),
    ownership: String(rawBook.ownership || "public"),
    editable: Boolean(rawBook.editable),
    chapters: safeChapters
  };
}

function sanitizeBookText(input) {
  if (input === null || input === undefined) {
    return "";
  }
  const lines = String(input)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => stripMarkdownLine(line));
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function ensureProgress(bookId) {
  if (!state.progressByBook[bookId]) {
    state.progressByBook[bookId] = {
      unlockedChapter: 0,
      passedChapters: {},
      masteredWords: {}
    };
  }
}

function switchView(viewName) {
  Object.entries(elements.views).forEach(([name, view]) => {
    const active = name === viewName;
    view.classList.toggle("active", active);
    const tab = [...elements.tabs].find((node) => node.dataset.view === name);
    if (tab) {
      tab.classList.toggle("active", active);
    }
  });
  elements.bottomNavButtons.forEach((btn) => {
    const name = btn.dataset.bottomNav;
    btn.classList.toggle("active", name === viewName);
  });

  if (viewName === "reader") {
    document.body.classList.add("immersive-mode");
    setReaderUiVisible(false);
    renderReader();
  } else {
    document.body.classList.remove("immersive-mode");
  }

  if (viewName === "shelf" && SERVER_MODE) {
    void refreshShelfFromServer();
  }

  if (viewName === "profile") {
    if (SERVER_MODE && state.auth.authenticated) {
      void refreshQuota().then(renderAuthPanel);
      void refreshReadingHistory().then(renderReadingHistoryPanel);
    }
    renderProfile();
    renderReadingHistoryPanel();
  }
}

function viewFromHash() {
  const hash = String(window.location.hash || "").replace(/^#/, "").trim();
  if (!hash) {
    return null;
  }
  return Object.prototype.hasOwnProperty.call(elements.views, hash) ? hash : null;
}

function isViewActive(viewName) {
  const target = elements.views[viewName];
  return Boolean(target && target.classList.contains("active"));
}

function setReaderUiVisible(visible) {
  state.readerUiVisible = visible;
  elements.readerStage.classList.toggle("ui-hidden", !visible);
  if (!visible) {
    hideTranslationCard();
  }
  scheduleReaderLayoutMetrics();
}

function toggleReaderUi() {
  setReaderUiVisible(!state.readerUiVisible);
}

function scheduleReaderLayoutMetrics() {
  if (layoutRaf) {
    cancelAnimationFrame(layoutRaf);
  }
  layoutRaf = requestAnimationFrame(() => {
    layoutRaf = 0;
    updateReaderLayoutMetrics();
  });
}

function updateReaderLayoutMetrics() {
  const stage = elements.readerStage;
  const sheet = elements.readerBottomSheet;
  if (!stage || !sheet) {
    return;
  }
  const sheetHeight = Math.max(0, Math.round(sheet.getBoundingClientRect().height));
  stage.style.setProperty("--reader-sheet-height", `${sheetHeight}px`);
}

function renderShelf() {
  elements.bookshelfList.innerHTML = "";
  if (state.books.length === 0) {
    elements.bookshelfList.innerHTML = "<p>暂无小说，请先导入。</p>";
    return;
  }

  const books = [...state.books].sort((a, b) => Number(a.sortOrder || 0) - Number(b.sortOrder || 0));
  const personalBooks = books.filter((book) => book.ownership === "personal");
  const publicBooks = books.filter((book) => book.ownership !== "personal");

  function renderBookCard(book) {
    ensureProgress(book.id);
    const progress = state.progressByBook[book.id];
    const chapterCount = book.chapters.length;
    const unlocked = Math.min(progress.unlockedChapter + 1, chapterCount);
    const coverNode = book.coverUrl
      ? `<img src="${escapeAttr(book.coverUrl)}" alt="${escapeAttr(book.title)} 封面" style="width:100%;height:180px;object-fit:cover;border-radius:10px;margin-bottom:8px;border:1px solid #d9e3f5;">`
      : "";
    const categoryNode = book.category ? `<p style="margin:0 0 8px;color:#355084;font-size:0.8rem;">分类：${escapeHtml(book.category)}</p>` : "";
    const ownershipNode =
      book.ownership === "personal"
        ? `<p style="margin:0 0 8px;color:#0b6c3c;font-size:0.8rem;">标签：个人书架</p>`
        : `<p style="margin:0 0 8px;color:#6b7280;font-size:0.8rem;">标签：公共书架</p>`;
    const checkboxNode =
      state.bookManageMode && book.ownership === "personal"
        ? `<label class="inline-switch"><input type="checkbox" data-select-personal="${escapeAttr(book.id)}" ${state.selectedPersonalBookIds[book.id] ? "checked" : ""}> 选择</label>`
        : "";
    const actionsNode =
      state.auth.authenticated && book.ownership === "personal"
        ? `<div class="actions">
            <button data-rename-personal="${escapeAttr(book.id)}" type="button">重命名</button>
            <button data-cover-personal="${escapeAttr(book.id)}" type="button">封面URL</button>
            <button data-upload-cover-personal="${escapeAttr(book.id)}" type="button">上传封面</button>
            <button data-delete-personal="${escapeAttr(book.id)}" type="button">删除</button>
          </div>
          <input data-upload-input="${escapeAttr(book.id)}" type="file" accept=".jpg,.jpeg,.png,.webp" style="display:none;">`
        : "";
    return `
      <article class="book-item">
        ${coverNode}
        <h3>${escapeHtml(book.title)}</h3>
        ${categoryNode}
        ${ownershipNode}
        ${checkboxNode}
        <p>${escapeHtml(book.description || "双语小说")}</p>
        <p>章节：${chapterCount} ｜ 已解锁：${unlocked}</p>
        <button data-open-book="${escapeAttr(book.id)}" class="primary-button">进入阅读</button>
        ${actionsNode}
      </article>
    `;
  }

  function renderSection(title, booksInSection, emptyText) {
    const body = booksInSection.length > 0
      ? `<div class="book-grid">${booksInSection.map(renderBookCard).join("")}</div>`
      : `<p class="shelf-empty">${escapeHtml(emptyText)}</p>`;
    return `
      <section class="shelf-section">
        <div class="shelf-section-head">
          <h3>${escapeHtml(title)}</h3>
          <span class="shelf-count">${booksInSection.length} 本</span>
        </div>
        ${body}
      </section>
    `;
  }

  elements.bookshelfList.innerHTML = [
    renderSection("个人书架", personalBooks, "你还没有个人书籍，可去生成器创建。"),
    renderSection("公共书架", publicBooks, "当前没有公共书籍，请到书架后台上传。"),
  ].join("");

  elements.bookshelfList.querySelectorAll("button[data-open-book]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeBookId = button.dataset.openBook;
      ensureProgress(state.activeBookId);
      const progress = state.progressByBook[state.activeBookId];
      state.activeChapterIndex = Math.min(progress.unlockedChapter, currentBook().chapters.length - 1);
      state.activePageIndex = 0;
      saveState();
      switchView("reader");
    });
  });

  elements.bookshelfList.querySelectorAll("input[data-select-personal]").forEach((node) => {
    node.addEventListener("change", () => {
      const id = node.dataset.selectPersonal;
      state.selectedPersonalBookIds[id] = Boolean(node.checked);
      renderAuthPanel();
    });
  });

  elements.bookshelfList.querySelectorAll("button[data-rename-personal]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bookId = button.dataset.renamePersonal;
      const book = state.books.find((item) => item.id === bookId);
      const nextTitle = window.prompt("输入新的书名：", book?.title || "");
      if (!nextTitle) {
        return;
      }
      await patchPersonalBook(bookId, { title: nextTitle });
    });
  });

  elements.bookshelfList.querySelectorAll("button[data-cover-personal]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bookId = button.dataset.coverPersonal;
      const nextUrl = window.prompt("输入封面URL：", "");
      if (!nextUrl) {
        return;
      }
      await patchPersonalBook(bookId, { coverUrl: nextUrl });
    });
  });

  elements.bookshelfList.querySelectorAll("button[data-upload-cover-personal]").forEach((button) => {
    button.addEventListener("click", () => {
      const bookId = button.dataset.uploadCoverPersonal;
      const input = [...elements.bookshelfList.querySelectorAll("input[data-upload-input]")].find(
        (node) => node.dataset.uploadInput === bookId
      );
      if (input) {
        input.click();
      }
    });
  });

  elements.bookshelfList.querySelectorAll("input[data-upload-input]").forEach((input) => {
    input.addEventListener("change", async () => {
      const bookId = input.dataset.uploadInput;
      const file = input.files && input.files[0];
      if (!file) {
        return;
      }
      await uploadPersonalBookCover(bookId, file);
      input.value = "";
    });
  });

  elements.bookshelfList.querySelectorAll("button[data-delete-personal]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bookId = button.dataset.deletePersonal;
      if (!window.confirm("确认删除这本个人书籍？")) {
        return;
      }
      await deletePersonalBook(bookId);
    });
  });
  renderAuthPanel();
}

async function patchPersonalBook(bookId, payload) {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  try {
    await apiFetchJSON(`${API_BASE}/user/books/${encodeURIComponent(bookId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    });
    await loadBooksFromServer();
    renderShelf();
    renderAuthPanel();
  } catch (err) {
    alert(`更新失败：${err.message}`);
  }
}

async function uploadPersonalBookCover(bookId, file) {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  try {
    const formData = new FormData();
    formData.append("file", file);
    await apiFetchJSON(`${API_BASE}/user/books/${encodeURIComponent(bookId)}/cover/upload`, {
      method: "POST",
      body: formData
    });
    await loadBooksFromServer();
    renderShelf();
    renderAuthPanel();
  } catch (err) {
    alert(`封面上传失败：${err.message}`);
  }
}

async function deletePersonalBook(bookId) {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  try {
    await apiFetchJSON(`${API_BASE}/user/books/${encodeURIComponent(bookId)}`, { method: "DELETE" });
    await loadBooksFromServer();
    renderShelf();
    renderAuthPanel();
  } catch (err) {
    alert(`删除失败：${err.message}`);
  }
}

async function onBatchDeleteBooks() {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  const ids = Object.entries(state.selectedPersonalBookIds)
    .filter(([, checked]) => Boolean(checked))
    .map(([id]) => id);
  if (ids.length === 0) {
    alert("请先勾选个人书籍。");
    return;
  }
  if (!window.confirm(`确认批量删除 ${ids.length} 本个人书籍？`)) {
    return;
  }
  try {
    await apiFetchJSON(`${API_BASE}/user/books/batch-delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookIds: ids })
    });
    state.selectedPersonalBookIds = {};
    await loadBooksFromServer();
    renderShelf();
    renderAuthPanel();
  } catch (err) {
    alert(`批量删除失败：${err.message}`);
  }
}

function currentBook() {
  return state.books.find((book) => book.id === state.activeBookId) || null;
}

function currentChapter() {
  const book = currentBook();
  if (!book) {
    return null;
  }
  return book.chapters[state.activeChapterIndex] || null;
}

function renderReader() {
  applyReaderAppearance();
  const book = currentBook();
  if (!book) {
    elements.readerBookTitle.textContent = "未选择小说";
    elements.readerChapterTitle.textContent = "请先去书架导入或选择一本小说";
    elements.chapterSelect.innerHTML = "";
    elements.readingPanel.innerHTML = "<p class='hint'>暂无阅读内容</p>";
    elements.pageIndicator.textContent = "0 / 0";
    elements.startQuiz.disabled = true;
    elements.prevChapter.disabled = true;
    elements.nextChapter.disabled = true;
    scheduleReaderLayoutMetrics();
    return;
  }

  ensureProgress(book.id);
  const progress = state.progressByBook[book.id];
  const maxAvailable = Math.min(progress.unlockedChapter, book.chapters.length - 1);
  if (state.activeChapterIndex > maxAvailable) {
    state.activeChapterIndex = maxAvailable;
  }

  elements.readerBookTitle.textContent = book.title;
  renderChapterSelect(book, progress);
  renderCurrentChapter();
  updateProgressPanel();
  scheduleReaderLayoutMetrics();
}

function renderChapterSelect(book, progress) {
  elements.chapterSelect.innerHTML = "";
  book.chapters.forEach((chapter, index) => {
    const unlocked = index <= progress.unlockedChapter;
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = unlocked ? `${index + 1}. ${chapter.title}` : `🔒 ${index + 1}. ${chapter.title}`;
    option.disabled = !unlocked;
    if (index === state.activeChapterIndex) {
      option.selected = true;
    }
    elements.chapterSelect.appendChild(option);
  });
}

function onChapterChange(event) {
  state.pendingChapterAdvance = false;
  const index = Number(event.target.value);
  const progress = state.progressByBook[state.activeBookId];
  if (index > progress.unlockedChapter) {
    alert("该章节未解锁，请先完成前一章单词过关。");
    event.target.value = String(state.activeChapterIndex);
    return;
  }
  state.activeChapterIndex = index;
  state.activePageIndex = 0;
  renderCurrentChapter();
  saveState();
  void reportReadingHistory();
}

function onReaderStyleChange() {
  state.settings.fontSize = Number(elements.fontSize.value);
  state.settings.lineHeight = Number(elements.lineHeight.value);
  state.settings.readerTheme = String(elements.readerTheme.value || "paper");
  state.settings.nightMode = Boolean(elements.nightMode.checked);
  state.settings.showChinese = Boolean(elements.showChinese.checked);
  state.cachedPagesKey = "";
  renderCurrentChapter();
  scheduleReaderLayoutMetrics();
  saveState();
}

function applyReaderAppearance() {
  const readerTheme = ["paper", "green"].includes(String(state.settings.readerTheme || ""))
    ? String(state.settings.readerTheme)
    : "paper";
  const nightMode = Boolean(state.settings.nightMode);
  state.settings.readerTheme = readerTheme;
  state.settings.nightMode = nightMode;

  elements.readerTheme.value = readerTheme;
  elements.nightMode.checked = nightMode;
  elements.readerStage.dataset.readerTheme = readerTheme;
  elements.readerStage.dataset.night = nightMode ? "1" : "0";

  // Set CSS vars on the stage so measurement/pagination elements can inherit them too.
  elements.readerStage.style.setProperty("--reader-font-size", `${state.settings.fontSize}px`);
  elements.readerStage.style.setProperty("--reader-line-height", String(state.settings.lineHeight));
}

function renderCurrentChapter() {
  const chapter = currentChapter();
  if (!chapter) {
    return;
  }

  elements.fontSize.value = String(state.settings.fontSize);
  elements.lineHeight.value = String(state.settings.lineHeight);
  applyReaderAppearance();
  elements.showChinese.checked = Boolean(state.settings.showChinese);
  elements.readerChapterTitle.textContent = chapter.title;

  const viewportKey = getPaginationViewportKey();
  const pagesKey = [
    state.activeBookId,
    state.activeChapterIndex,
    state.settings.fontSize,
    state.settings.lineHeight,
    viewportKey
  ].join(":");

  if (state.cachedPagesKey !== pagesKey) {
    const oldKey = state.cachedPagesKey;
    const oldCount = Array.isArray(state.pages) ? state.pages.length : 0;
    const oldIndex = Number(state.activePageIndex || 0);
    const nextPages = paginateChapter(chapter.english, state.settings.fontSize, state.settings.lineHeight);
    state.pages = nextPages;
    state.cachedPagesKey = pagesKey;

    // Preserve reading position when only layout/style changes (same book + chapter).
    const sameChapter = Boolean(
      oldKey &&
        String(oldKey).startsWith(`${state.activeBookId}:${state.activeChapterIndex}:`)
    );
    if (sameChapter && oldCount > 0 && nextPages.length > 0) {
      const ratio = Math.max(0, Math.min(1, oldIndex / oldCount));
      state.activePageIndex = Math.max(0, Math.min(nextPages.length - 1, Math.round(ratio * nextPages.length)));
    } else {
      state.activePageIndex = 0;
    }
  }

  if (state.activePageIndex >= state.pages.length) {
    state.activePageIndex = state.pages.length - 1;
  }

  paintCurrentPage(true);
  updateGateStatus();
  hideTranslationCard();
  void reportReadingHistory();
}

function splitParagraphByLimit(paragraph, pageCharLimit) {
  const segments = [];
  if (!paragraph.trim()) {
    return segments;
  }

  const hasWhitespace = /\s/.test(paragraph);
  if (!hasWhitespace) {
    const cjkChunks = paragraph.match(new RegExp(`.{1,${Math.max(80, Math.floor(pageCharLimit * 0.9))}}`, "g")) || [paragraph];
    return cjkChunks.map((item) => item.trim()).filter(Boolean);
  }

  const words = paragraph.split(/\s+/).filter(Boolean);
  let current = "";
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= pageCharLimit) {
      current = candidate;
      return;
    }
    if (current.trim()) {
      segments.push(current.trim());
      current = word;
      return;
    }
    const hardChunks = word.match(new RegExp(`.{1,${Math.max(24, Math.floor(pageCharLimit * 0.8))}}`, "g")) || [word];
    hardChunks.forEach((piece) => {
      if (piece.trim()) {
        segments.push(piece.trim());
      }
    });
    current = "";
  });
  if (current.trim()) {
    segments.push(current.trim());
  }
  return segments;
}

function paginateChapterByChars(text, fontSize, lineHeight) {
  const chunks = [];
  const normalized = text
    .replace(/\r/g, "")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  const joined = normalized.length > 0 ? normalized : [text];

  const scale = 20 / Math.max(16, fontSize);
  const lineScale = 1.7 / Math.max(1.4, lineHeight);
  const pageCharLimit = Math.max(480, Math.floor(1450 * scale * lineScale));

  let current = "";
  joined.forEach((paragraph) => {
    const paragraphWithGap = `${paragraph}\n\n`;
    if ((current + paragraphWithGap).length <= pageCharLimit) {
      current += paragraphWithGap;
      return;
    }
    if (current.trim()) {
      chunks.push(current.trim());
      current = "";
    }
    if (paragraphWithGap.length <= pageCharLimit) {
      current = paragraphWithGap;
      return;
    }

    const segments = splitParagraphByLimit(paragraph, pageCharLimit);
    segments.forEach((segment, segmentIndex) => {
      if (!segment.trim()) {
        return;
      }
      if (segmentIndex < segments.length - 1) {
        chunks.push(segment.trim());
      } else {
        current = `${segment}\n\n`;
      }
    });
  });

  if (current.trim()) {
    chunks.push(current.trim());
  }

  return chunks.length > 0 ? chunks : [text];
}

let pageMeasureFrame = null;
let pageMeasureContent = null;

function getPaginationViewportKey() {
  const width = Math.max(0, Math.round(elements.readingPanel?.clientWidth || 0));
  const height = Math.max(0, Math.round(elements.readingPanel?.clientHeight || 0));
  return `${width}x${height}`;
}

function ensurePageMeasure(panelWidth, panelHeight) {
  if (!elements.readerStage) {
    return false;
  }
  if (!pageMeasureFrame || !pageMeasureContent || !pageMeasureFrame.isConnected) {
    pageMeasureFrame = document.createElement("section");
    pageMeasureFrame.className = "page-frame";
    pageMeasureFrame.setAttribute("aria-hidden", "true");
    pageMeasureFrame.style.position = "absolute";
    pageMeasureFrame.style.left = "-99999px";
    pageMeasureFrame.style.top = "0";
    pageMeasureFrame.style.visibility = "hidden";
    pageMeasureFrame.style.pointerEvents = "none";

    pageMeasureContent = document.createElement("div");
    pageMeasureContent.className = "page-content";
    pageMeasureFrame.appendChild(pageMeasureContent);
    elements.readerStage.appendChild(pageMeasureFrame);
  }
  pageMeasureFrame.style.width = `${Math.max(1, panelWidth)}px`;
  pageMeasureFrame.style.height = `${Math.max(1, panelHeight)}px`;
  return true;
}

function buildMeasureHtml(paragraphs) {
  return paragraphs
    .map((paragraph) => `<p class="paragraph">${escapeHtml(paragraph)}</p>`)
    .join("");
}

function measurePageFits(paragraphs) {
  if (!pageMeasureContent) {
    return true;
  }
  pageMeasureContent.innerHTML = buildMeasureHtml(paragraphs);
  return pageMeasureContent.scrollHeight <= pageMeasureContent.clientHeight + 1;
}

function splitParagraphByMeasure(paragraph) {
  const text = String(paragraph || "").trim();
  if (!text) {
    return [];
  }
  const segments = [];
  const hasWhitespace = /\s/.test(text);

  if (hasWhitespace) {
    const words = text.split(/\s+/).filter(Boolean);
    let start = 0;
    while (start < words.length) {
      let lo = start + 1;
      let hi = words.length;
      let best = start + 1;
      while (lo <= hi) {
        const mid = Math.floor((lo + hi) / 2);
        const candidate = words.slice(start, mid).join(" ");
        if (measurePageFits([candidate])) {
          best = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      const segment = words.slice(start, best).join(" ").trim();
      if (!segment) {
        break;
      }
      segments.push(segment);
      start = best;
    }
    return segments;
  }

  // CJK / no-whitespace fallback: binary search by substring length.
  let start = 0;
  while (start < text.length) {
    let lo = start + 1;
    let hi = text.length;
    let best = start + 1;
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      const candidate = text.slice(start, mid);
      if (measurePageFits([candidate])) {
        best = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    const segment = text.slice(start, best).trim();
    if (!segment) {
      break;
    }
    segments.push(segment);
    start = best;
  }
  return segments;
}

function paginateChapterByMeasure(text) {
  const panelWidth = Math.max(0, Math.round(elements.readingPanel?.clientWidth || 0));
  const panelHeight = Math.max(0, Math.round(elements.readingPanel?.clientHeight || 0));
  if (panelWidth < 240 || panelHeight < 240) {
    return null;
  }
  if (!ensurePageMeasure(panelWidth, panelHeight)) {
    return null;
  }

  const cleaned = sanitizeBookText(text);
  const paragraphs = cleaned
    .replace(/\r/g, "")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  const joined = paragraphs.length > 0 ? paragraphs : [cleaned.trim()].filter(Boolean);
  if (joined.length === 0) {
    return null;
  }

  const pages = [];
  let currentParas = [];
  let index = 0;
  while (index < joined.length) {
    const paragraph = joined[index];
    const candidate = [...currentParas, paragraph];
    if (measurePageFits(candidate)) {
      currentParas = candidate;
      index += 1;
      continue;
    }
    if (currentParas.length > 0) {
      pages.push(currentParas.join("\n\n").trim());
      currentParas = [];
      continue;
    }

    // Single paragraph too large: split it, push full pages, keep last segment to continue.
    const segments = splitParagraphByMeasure(paragraph);
    if (segments.length === 0) {
      // Fallback: avoid infinite loop.
      pages.push(paragraph.trim());
      index += 1;
      continue;
    }
    segments.forEach((segment, segmentIndex) => {
      if (segmentIndex < segments.length - 1) {
        pages.push(segment.trim());
      } else {
        currentParas = [segment.trim()];
      }
    });
    index += 1;
  }

  if (currentParas.length > 0) {
    pages.push(currentParas.join("\n\n").trim());
  }
  return pages.length > 0 ? pages : null;
}

function paginateChapter(text, fontSize, lineHeight) {
  // Prefer real viewport pagination when reader view is visible; fallback to char-based splits.
  if (isViewActive("reader")) {
    const measured = paginateChapterByMeasure(text);
    if (Array.isArray(measured) && measured.length > 0) {
      return measured;
    }
  }
  return paginateChapterByChars(String(text || ""), fontSize, lineHeight);
}

function renderPageParagraphs(pageText, pageIndex) {
  const paragraphs = String(pageText || "")
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  return paragraphs
    .map((paragraph, index) => {
      const normalizedParagraph = stripMarkdownLine(paragraph);
      if (!normalizedParagraph) {
        return "";
      }
      const anchorId = `p-${index}`;
      const anchorKey = buildAnchorKey(anchorId, pageIndex);
      const count = commentCount(anchorKey);
      const preview = normalizedParagraph.replace(/\s+/g, " ").slice(0, 36);
      const badgeClass = count > 0 ? "comment-badge" : "comment-badge hidden";
      return `<p class="paragraph" data-anchor-id="${anchorId}" data-page-index="${pageIndex}" data-anchor-preview="${escapeAttr(
        preview
      )}">${decorateWords(escapeHtml(normalizedParagraph))}<button type="button" class="${badgeClass}" data-anchor-id="${anchorId}" data-page-index="${pageIndex}">${displayCommentCount(
        count
      )}</button></p>`;
    })
    .join("");
}

function paintCurrentPage(rebuildPages = false) {
  if (state.pages.length === 0) {
    elements.readingPanel.innerHTML = "<div class='page-track'><section class='page-frame'><div class='page-content'><p class='hint'>本页暂无内容</p></div></section></div>";
    elements.pageIndicator.textContent = "0 / 0";
    return;
  }

  if (rebuildPages) {
    const pagesHtml = state.pages
      .map((pageText, pageIndex) => {
        const pageBody = renderPageParagraphs(pageText, pageIndex) || "<p class='hint'>本页暂无内容</p>";
        return `<section class="page-frame" data-page-index="${pageIndex}"><div class="page-content">${pageBody}</div></section>`;
      })
      .join("");
    elements.readingPanel.innerHTML = `<div class="page-track">${pagesHtml}</div>`;
  }

  const panelWidth = Math.max(1, elements.readingPanel.clientWidth || 1);
  const targetLeft = state.activePageIndex * panelWidth;
  const currentLeft = elements.readingPanel.scrollLeft;
  if (Math.abs(currentLeft - targetLeft) > 2) {
    elements.readingPanel.scrollTo({
      left: targetLeft,
      behavior: rebuildPages ? "auto" : "smooth",
    });
  }
  renderChinesePanel();
  scheduleReaderLayoutMetrics();
  elements.pageIndicator.textContent = `${state.activePageIndex + 1} / ${state.pages.length}`;
  elements.prevPage.disabled = state.activePageIndex <= 0;
  elements.nextPage.disabled = state.activePageIndex >= state.pages.length - 1;
}

function renderChinesePanel() {
  const chapter = currentChapter();
  if (!chapter) {
    elements.chinesePanel.classList.add("hidden");
    elements.chinesePanel.innerHTML = "";
    return;
  }

  if (!state.settings.showChinese) {
    elements.chinesePanel.classList.add("hidden");
    return;
  }

  const chineseRaw = chapter.chinese ? sanitizeBookText(chapter.chinese) : "";
  const chineseText = chineseRaw ? escapeHtml(chineseRaw).replace(/\n/g, "<br>") : "本章暂无中文对照";
  elements.chinesePanel.innerHTML = `<strong>中文对照</strong><p>${chineseText}</p>`;
  elements.chinesePanel.classList.remove("hidden");
}

function decorateWords(escapedText) {
  return escapedText.replace(/\b([A-Za-z][A-Za-z'-]*)\b/g, (_match, word) => {
    return `<span class="word" data-word="${word.toLowerCase()}">${word}</span>`;
  });
}

function turnPage(direction) {
  if (state.pages.length === 0) {
    return;
  }
  const nextIndex = state.activePageIndex + direction;
  if (nextIndex < 0 || nextIndex >= state.pages.length) {
    return;
  }
  state.activePageIndex = nextIndex;
  paintCurrentPage();
  updateGateStatus();
  void reportReadingHistory();
}

function unlockChapterAtLeast(index) {
  const book = currentBook();
  if (!book) {
    return;
  }
  ensureProgress(book.id);
  const progress = state.progressByBook[book.id];
  const normalized = Math.max(0, Math.min(index, book.chapters.length - 1));
  if (progress.unlockedChapter < normalized) {
    progress.unlockedChapter = normalized;
    saveState();
  }
}

function jumpToChapter(index) {
  const book = currentBook();
  if (!book) {
    return false;
  }
  if (index < 0 || index >= book.chapters.length) {
    return false;
  }
  ensureProgress(book.id);
  const progress = state.progressByBook[book.id];
  if (index > progress.unlockedChapter) {
    return false;
  }

  state.activeChapterIndex = index;
  state.activePageIndex = 0;
  state.cachedPagesKey = "";
  renderChapterSelect(book, progress);
  renderCurrentChapter();
  saveState();
  void reportReadingHistory();
  return true;
}

function navigateChapter(step) {
  const book = currentBook();
  if (!book) {
    return;
  }
  state.pendingChapterAdvance = false;
  if (step < 0) {
    if (state.activeChapterIndex <= 0) {
      alert("已经是第一章。");
      return;
    }
    jumpToChapter(state.activeChapterIndex - 1);
    return;
  }
  handleNextChapterRequest();
}

function handleNextChapterRequest() {
  const book = currentBook();
  const chapter = currentChapter();
  if (!book || !chapter) {
    return;
  }

  const currentIndex = state.activeChapterIndex;
  const nextIndex = currentIndex + 1;
  if (nextIndex >= book.chapters.length) {
    alert("已经是最后一章。");
    return;
  }

  const needQuiz = chapterNeedsQuiz(currentIndex);
  const passed = isChapterPassed(book.id, currentIndex);

  if (needQuiz && !passed) {
    const words = chapterTargetWords(chapter);
    if (words.length === 0) {
      autoPassChapterForNoWords({ silent: true });
      unlockChapterAtLeast(nextIndex);
      jumpToChapter(nextIndex);
      return;
    }
    state.pendingChapterAdvance = true;
    beginQuiz();
    return;
  }

  unlockChapterAtLeast(nextIndex);
  jumpToChapter(nextIndex);
}

function isChapterPassed(bookId, chapterIndex) {
  const progress = state.progressByBook[bookId];
  return Boolean(progress.passedChapters[String(chapterIndex)]);
}

function chapterNeedsQuiz(chapterIndex) {
  const book = currentBook();
  if (!book) {
    return false;
  }
  const chapter = book.chapters[chapterIndex];
  return Array.isArray(chapter?.targetWords) && chapter.targetWords.length > 0;
}

function chapterTargetWords(chapter) {
  return Array.isArray(chapter.targetWords) ? chapter.targetWords : [];
}

function updateGateStatus() {
  const book = currentBook();
  const chapter = currentChapter();
  if (!book || !chapter) {
    return;
  }
  elements.prevChapter.disabled = state.activeChapterIndex <= 0;
  elements.nextChapter.disabled = state.activeChapterIndex >= book.chapters.length - 1;

  const progress = state.progressByBook[book.id];
  const passed = isChapterPassed(book.id, state.activeChapterIndex);
  const needQuiz = chapterNeedsQuiz(state.activeChapterIndex);
  const atLastPage = state.activePageIndex >= state.pages.length - 1;

  if (!needQuiz) {
    elements.gateStatus.textContent = "本章未配置闯关任务，可直接进入下一章。";
    elements.startQuiz.disabled = true;
    return;
  }

  if (passed) {
    elements.gateStatus.textContent = "本章已过关，可进入下一章。";
    elements.startQuiz.disabled = true;
    if (progress.unlockedChapter < state.activeChapterIndex + 1) {
      progress.unlockedChapter = Math.min(state.activeChapterIndex + 1, book.chapters.length - 1);
      saveState();
      renderChapterSelect(book, progress);
    }
    return;
  }

  if (!atLastPage) {
    elements.gateStatus.textContent = "请先阅读到本章末页，再进行单词过关。";
    elements.startQuiz.disabled = true;
    return;
  }

  elements.gateStatus.textContent = "已到末页，请完成单词过关后解锁下一章。";
  elements.startQuiz.disabled = false;
}

function buildReadingHistoryPayload() {
  if (!state.auth.authenticated) {
    return null;
  }
  const book = currentBook();
  const chapter = currentChapter();
  if (!book || !chapter) {
    return null;
  }
  return {
    bookId: book.id,
    chapterIndex: Number(state.activeChapterIndex || 0),
    pageIndex: Number(state.activePageIndex || 0),
    bookTitle: book.title || "",
    chapterTitle: chapter.title || ""
  };
}

async function reportReadingHistory(force = false) {
  if (!SERVER_MODE || !state.auth.authenticated) {
    return;
  }
  const payload = buildReadingHistoryPayload();
  if (!payload) {
    return;
  }
  const key = `${payload.bookId}:${payload.chapterIndex}:${payload.pageIndex}`;
  const now = Date.now();
  if (!force && key === state.historyLastReportKey && now - state.historyLastReportAt < 30000) {
    return;
  }
  state.historyLastReportKey = key;
  state.historyLastReportAt = now;
  try {
    await apiFetchJSON(`${API_BASE}/user/reading-history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (_err) {
    // ignore
  }
}

function buildChapterDictionary(chapter) {
  const dictionary = { ...baseDictionary };
  chapterTargetWords(chapter).forEach((entry) => {
    const word = String(entry.word || "").toLowerCase();
    const translation = String(entry.translation || "").trim();
    if (!word || !translation || translation === "未提供翻译") {
      return;
    }
    dictionary[word] = translation;
  });
  return dictionary;
}

function onReadingPanelClick(event) {
  if (Date.now() < suppressTapUntil) {
    return;
  }
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  if (target.closest(".comment-badge")) {
    const badge = target.closest(".comment-badge");
    const anchorId = badge?.dataset.anchorId;
    const pageIndex = Number(badge?.dataset.pageIndex ?? state.activePageIndex);
    const paragraph = badge?.closest(".paragraph");
    if (anchorId) {
      openCommentList(anchorId, paragraph?.dataset.anchorPreview || "", pageIndex);
    }
    return;
  }

  if (target.classList.contains("word")) {
    onWordClickTarget(target);
    return;
  }

  hideTranslationCard();

  if (longPressTriggered) {
    longPressTriggered = false;
    return;
  }

  const selection = window.getSelection();
  if (selection && !selection.isCollapsed) {
    return;
  }
  const panelRect = elements.readingPanel.getBoundingClientRect();
  const panelWidth = Math.max(1, panelRect.width);
  const tapX = Number(event.clientX || 0) - panelRect.left;
  const tapRatio = tapX / panelWidth;

  if (tapRatio <= TAP_ZONE_RATIO) {
    turnPage(-1);
    return;
  }
  if (tapRatio >= 1 - TAP_ZONE_RATIO) {
    turnPage(1);
    return;
  }
  toggleReaderUi();
}

function onReaderStageClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.closest(".word") || target.closest("#translation-card")) {
    return;
  }
  hideTranslationCard();
}

function onReadingPanelPointerDown(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  pointerStartX = Number(event.clientX || 0);
  pointerStartY = Number(event.clientY || 0);
  pointerMoved = false;

  if (target.closest(".word") || target.closest(".comment-badge")) {
    return;
  }

  const paragraph = target.closest(".paragraph");
  if (!paragraph) {
    return;
  }

  clearLongPressTimer();
  longPressTriggered = false;
  longPressTimer = setTimeout(() => {
    longPressTriggered = true;
    const anchorId = paragraph.dataset.anchorId;
    const pageIndex = Number(paragraph.dataset.pageIndex ?? state.activePageIndex);
    if (!anchorId) {
      return;
    }
    openCommentInput(anchorId, paragraph.dataset.anchorPreview || "", pageIndex);
  }, 550);
}

function onReadingPanelPointerMove(event) {
  const dx = Math.abs(Number(event.clientX || 0) - pointerStartX);
  const dy = Math.abs(Number(event.clientY || 0) - pointerStartY);
  if (dx > 6 || dy > 6) {
    pointerMoved = true;
    clearLongPressTimer();
  }
}

function onReadingPanelPointerUp() {
  if (pointerMoved) {
    suppressTapUntil = Date.now() + 260;
  }
  clearLongPressTimer();
}

function onReadingPanelScroll() {
  if (readingScrollRaf) {
    cancelAnimationFrame(readingScrollRaf);
  }
  readingScrollRaf = requestAnimationFrame(() => {
    readingScrollRaf = 0;
    if (state.pages.length === 0) {
      return;
    }
    const panelWidth = Math.max(1, elements.readingPanel.clientWidth || 1);
    const index = Math.max(0, Math.min(state.pages.length - 1, Math.round(elements.readingPanel.scrollLeft / panelWidth)));
    if (index === state.activePageIndex) {
      return;
    }
    state.activePageIndex = index;
    elements.pageIndicator.textContent = `${state.activePageIndex + 1} / ${state.pages.length}`;
    elements.prevPage.disabled = state.activePageIndex <= 0;
    elements.nextPage.disabled = state.activePageIndex >= state.pages.length - 1;
    updateGateStatus();
    void reportReadingHistory();
  });
}

function clearLongPressTimer() {
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
}

async function onWordClickTarget(target) {
  const word = String(target.dataset.word || "").toLowerCase();
  if (!word) {
    return;
  }
  const chapter = currentChapter();
  if (!chapter) {
    return;
  }
  const dictionary = buildChapterDictionary(chapter);
  const contextInfo = getWordContextInfo(target);
  const quickTranslation = dictionary[word] || state.translationCache[word] || "";

  speakingWord = word;
  elements.translationWord.textContent = word;
  elements.translationMeaning.textContent = quickTranslation || "查询中...";
  elements.translationCard.classList.remove("hidden");
  setReaderUiVisible(true);
  scheduleReaderLayoutMetrics();

  if (quickTranslation) {
    return;
  }

  const token = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  state.activeLookupToken = token;
  const lookup = await lookupTranslation(word, contextInfo);
  if (state.activeLookupToken !== token) {
    return;
  }

  if (lookup.lookup && lookup.lookup !== word) {
    elements.translationWord.textContent = lookup.lookup;
  } else {
    elements.translationWord.textContent = word;
  }
  elements.translationMeaning.textContent = lookup.translation || "暂未查到释义";
}

function getWordContextInfo(target) {
  const paragraph = target.closest(".paragraph");
  if (!paragraph) {
    return { context: "", prevWord: "", nextWord: "" };
  }
  const wordNodes = [...paragraph.querySelectorAll(".word")];
  const index = wordNodes.indexOf(target);
  const prevWord = index > 0 ? String(wordNodes[index - 1].dataset.word || "") : "";
  const nextWord = index >= 0 && index + 1 < wordNodes.length ? String(wordNodes[index + 1].dataset.word || "") : "";

  const clone = paragraph.cloneNode(true);
  clone.querySelectorAll(".comment-badge").forEach((node) => node.remove());
  const context = clone.textContent.replace(/\s+/g, " ").trim().slice(0, 320);
  return { context, prevWord, nextWord };
}

function hideTranslationCard() {
  speakingWord = "";
  state.activeLookupToken = "";
  elements.translationCard.classList.add("hidden");
}

async function lookupTranslation(word, contextInfo = {}) {
  const normalizedWord = String(word || "").toLowerCase().trim();
  if (!normalizedWord) {
    return { lookup: normalizedWord, translation: "" };
  }

  const context = String(contextInfo.context || "");
  const prevWord = String(contextInfo.prevWord || "").toLowerCase();
  const nextWord = String(contextInfo.nextWord || "").toLowerCase();
  const requestKey = `${normalizedWord}|${prevWord}|${nextWord}|${context.slice(0, 120)}`;

  if (translationRequestCache.has(requestKey)) {
    return translationRequestCache.get(requestKey);
  }

  const requestPromise = (async () => {
    if (SERVER_MODE) {
      try {
        const params = new URLSearchParams({
          word: normalizedWord,
          context,
          prev: prevWord,
          next: nextWord
        });
        const response = await fetch(`${API_BASE}/public/dict?${params.toString()}`);
        if (response.ok) {
          const data = await response.json();
          const translation = String(data.translation || "").trim();
          const lookup = String(data.lookup || normalizedWord).trim();
          if (translation) {
            if (lookup === normalizedWord) {
              state.translationCache[normalizedWord] = translation;
              saveState();
            }
            return { lookup, translation };
          }
        }
      } catch (_error) {
        // 后端查询失败时走前端兜底
      }
    }

    const local = state.translationCache[normalizedWord];
    if (local) {
      return { lookup: normalizedWord, translation: local };
    }

    const fallback = await fetchMyMemoryTranslation(normalizedWord);
    if (fallback) {
      state.translationCache[normalizedWord] = fallback;
      saveState();
      return { lookup: normalizedWord, translation: fallback };
    }
    return { lookup: normalizedWord, translation: "" };
  })();

  translationRequestCache.set(requestKey, requestPromise);
  try {
    return await requestPromise;
  } finally {
    translationRequestCache.delete(requestKey);
  }
}

async function fetchTranslation(word) {
  const result = await lookupTranslation(word);
  return String(result.translation || "");
}

async function fetchMyMemoryTranslation(word) {
  try {
    const endpoint = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(word)}&langpair=en|zh-CN`;
    const response = await fetch(endpoint);
    if (!response.ok) {
      return "";
    }
    const data = await response.json();
    const translated = String(data?.responseData?.translatedText || "").trim();
    if (!translated || translated.toLowerCase() === word.toLowerCase()) {
      return "";
    }
    return translated;
  } catch (_error) {
    return "";
  }
}

function speakWord(word) {
  if (!word || !("speechSynthesis" in window)) {
    return;
  }
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = "en-US";
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

function buildAnchorKey(anchorId, pageIndex = state.activePageIndex) {
  return `${state.activeBookId}:${state.activeChapterIndex}:${pageIndex}:${anchorId}`;
}

function commentCount(anchorKey) {
  return Array.isArray(state.commentsByAnchor[anchorKey]) ? state.commentsByAnchor[anchorKey].length : 0;
}

function displayCommentCount(count) {
  return String(Math.min(99, count));
}

function openCommentInput(anchorId, preview, pageIndex = state.activePageIndex) {
  const anchorKey = buildAnchorKey(anchorId, pageIndex);
  state.commentContext = { anchorId, anchorKey, preview, pageIndex };
  elements.commentAnchorPreview.textContent = preview ? `锚点：${preview}` : "锚点：当前段落";
  elements.commentText.value = "";
  elements.commentInputDialog.showModal();
}

function submitCommentInput(event) {
  event.preventDefault();
  if (!state.commentContext) {
    return;
  }
  const text = elements.commentText.value.trim();
  if (!text) {
    return;
  }

  const key = state.commentContext.anchorKey;
  if (!Array.isArray(state.commentsByAnchor[key])) {
    state.commentsByAnchor[key] = [];
  }
  state.commentsByAnchor[key].unshift({
    text,
    createdAt: new Date().toISOString()
  });

  saveState();
  elements.commentInputDialog.close();
  paintCurrentPage(true);

  openCommentList(state.commentContext.anchorId, state.commentContext.preview, state.commentContext.pageIndex);
}

function openCommentList(anchorId, preview, pageIndex = state.activePageIndex) {
  const anchorKey = buildAnchorKey(anchorId, pageIndex);
  state.commentContext = { anchorId, anchorKey, preview, pageIndex };
  const list = state.commentsByAnchor[anchorKey] || [];
  elements.commentListTitle.textContent = `全部 ${list.length}`;
  elements.commentListAnchor.textContent = preview ? `锚点：${preview}` : "锚点：当前段落";

  if (list.length === 0) {
    elements.commentListBody.innerHTML = "<p class='hint'>还没有评论，长按这段文字添加第一条。</p>";
  } else {
    elements.commentListBody.innerHTML = list
      .map((item) => {
        const time = new Date(item.createdAt);
        const localTime = `${time.getFullYear()}-${pad(time.getMonth() + 1)}-${pad(time.getDate())} ${pad(
          time.getHours()
        )}:${pad(time.getMinutes())}`;
        return `
          <article class="comment-item">
            <p>${escapeHtml(item.text)}</p>
            <div class="comment-meta">${localTime}</div>
          </article>
        `;
      })
      .join("");
  }

  elements.commentListDialog.showModal();
}

function pad(num) {
  return String(num).padStart(2, "0");
}

function isMissingTranslation(translation) {
  const value = String(translation || "").trim();
  return !value || value === "未提供翻译";
}

async function resolveQuizWords(words) {
  const resolved = await Promise.all(
    words.map(async (entry) => {
      const word = String(entry?.word || "").trim();
      if (!word) {
        return null;
      }
      const lowerWord = word.toLowerCase();
      let translation = String(entry?.translation || "").trim();
      if (isMissingTranslation(translation)) {
        translation = state.translationCache[lowerWord] || "";
        if (!translation) {
          translation = await fetchTranslation(lowerWord);
        }
      }
      if (!translation) {
        translation = `待补充：${word}`;
      }
      state.translationCache[lowerWord] = translation;
      return { ...entry, word, translation };
    })
  );

  return resolved.filter(Boolean);
}

async function beginQuiz() {
  const book = currentBook();
  const chapter = currentChapter();
  if (!book || !chapter) {
    return;
  }
  if (!chapterNeedsQuiz(state.activeChapterIndex)) {
    alert("该章节不需要单词过关。");
    return;
  }

  const words = chapterTargetWords(chapter);
  if (words.length === 0) {
    autoPassChapterForNoWords();
    return;
  }

  const originalText = elements.startQuiz.textContent;
  elements.startQuiz.disabled = true;
  elements.startQuiz.textContent = "准备题目中...";

  try {
    const maxPool = Math.min(words.length, QUIZ_DRAW_COUNT);
    const quizPool = shuffle(words).slice(0, maxPool);
    const resolvedWords = await resolveQuizWords(quizPool);
    if (resolvedWords.length === 0) {
      autoPassChapterForNoWords();
      return;
    }

    const translationByWord = {};
    resolvedWords.forEach((item) => {
      translationByWord[item.word.toLowerCase()] = item.translation;
    });
    chapter.targetWords = chapterTargetWords(chapter).map((item) => {
      const word = String(item.word || "").trim();
      const lowerWord = word.toLowerCase();
      if (!word || !translationByWord[lowerWord]) {
        return item;
      }
      return { ...item, word, translation: translationByWord[lowerWord] };
    });
    saveState();

    const selected = shuffle([...resolvedWords]);
    const distractors = [...new Set(resolvedWords.map((item) => item.translation).filter(Boolean))];
    const fallbackOptions = ["暂未掌握", "需要复习", "不是这个"];

    state.quizQuestions = selected.map((entry, idx) => {
      const options = [entry.translation];
      shuffle(distractors)
        .filter((item) => item !== entry.translation)
        .slice(0, 3)
        .forEach((item) => options.push(item));

      fallbackOptions.forEach((item) => {
        if (options.length < 4 && item !== entry.translation && !options.includes(item)) {
          options.push(item);
        }
      });

      return {
        id: `q-${idx}`,
        word: entry.word,
        answer: entry.translation,
        options: shuffle([...new Set(options)])
      };
    });
    renderQuiz(chapter.title);
    elements.quizDialog.showModal();
  } finally {
    elements.startQuiz.textContent = originalText;
    updateGateStatus();
  }
}

function autoPassChapterForNoWords(options = {}) {
  const { silent = false } = options;
  const book = currentBook();
  if (!book) {
    return;
  }
  const progress = state.progressByBook[book.id];
  progress.passedChapters[String(state.activeChapterIndex)] = true;
  progress.unlockedChapter = Math.min(state.activeChapterIndex + 1, book.chapters.length - 1);
  saveState();
  renderChapterSelect(book, progress);
  updateGateStatus();
  if (!silent) {
    alert("本章未配置目标词汇，已自动判定通过并解锁下一章。");
  }
}

function renderQuiz(chapterTitle) {
  elements.quizSubtitle.textContent = `${chapterTitle} ｜ 正确率达到 80% 即可过关`;
  elements.quizQuestions.innerHTML = "";
  state.quizQuestions.forEach((question, index) => {
    const block = document.createElement("section");
    block.className = "quiz-question";
    const optionsHtml = question.options
      .map((option) => {
        return `
          <label>
            <input type="radio" name="${question.id}" value="${escapeHtml(option)}" required>
            ${escapeHtml(option)}
          </label>
        `;
      })
      .join("");
    block.innerHTML = `
      <p>${index + 1}. ${escapeHtml(question.word)} 的中文释义是？</p>
      ${optionsHtml}
    `;
    elements.quizQuestions.appendChild(block);
  });
}

function submitQuiz(event) {
  event.preventDefault();
  const formData = new FormData(elements.quizForm);
  let correct = 0;
  state.quizQuestions.forEach((question) => {
    const userAnswer = String(formData.get(question.id) || "");
    if (userAnswer === question.answer) {
      correct += 1;
    }
  });
  const total = state.quizQuestions.length;
  const score = total === 0 ? 0 : correct / total;

  const book = currentBook();
  const chapter = currentChapter();
  if (!book || !chapter) {
    return;
  }
  const progress = state.progressByBook[book.id];
  if (score >= PASS_RATE) {
    const currentIndex = state.activeChapterIndex;
    const shouldAdvance = state.pendingChapterAdvance;
    state.pendingChapterAdvance = false;
    progress.passedChapters[String(state.activeChapterIndex)] = true;
    chapterTargetWords(chapter).forEach((entry) => {
      progress.masteredWords[entry.word.toLowerCase()] = entry.translation;
    });
    progress.unlockedChapter = Math.min(state.activeChapterIndex + 1, book.chapters.length - 1);
    saveState();
    renderChapterSelect(book, progress);
    updateProgressPanel();
    elements.quizDialog.close();
    updateGateStatus();
    if (shouldAdvance && currentIndex < book.chapters.length - 1) {
      unlockChapterAtLeast(currentIndex + 1);
      jumpToChapter(currentIndex + 1);
      alert(`通过！得分 ${correct}/${total}，已进入下一章。`);
      return;
    }
    alert(`通过！得分 ${correct}/${total}，下一章已解锁。`);
    return;
  }

  state.pendingChapterAdvance = false;
  elements.quizDialog.close();
  alert(`未通过，得分 ${correct}/${total}。请复习后重试。`);
}

function updateProgressPanel() {
  const book = currentBook();
  if (!book) {
    elements.progressLabel.textContent = "0 / 3500";
    elements.progressFill.style.width = "0%";
    return;
  }
  const progress = state.progressByBook[book.id];
  const mastered = Object.keys(progress.masteredWords || {}).length;
  const goal = book.wordGoal || 3500;
  const percent = Math.min(100, Math.round((mastered / goal) * 100));

  elements.progressLabel.textContent = `${mastered} / ${goal}`;
  elements.progressFill.style.width = `${percent}%`;
}

function renderProfile() {
  elements.profileAge.value = state.profile.age;
  elements.profileStage.value = state.profile.stage;
  elements.profileTrack.value = state.profile.track;
  updateProgressPanel();
  renderAuthPanel();
  renderReadingHistoryPanel();
}

async function importBookFile(event) {
  if (!USER_CAN_UPLOAD) {
    alert("当前是读者模式，不能上传文档。请使用后台上传。");
    event.target.value = "";
    return;
  }
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  try {
    const content = await file.text();
    const lowerName = file.name.toLowerCase();
    let parsed;

    if (lowerName.endsWith(".json")) {
      parsed = JSON.parse(content);
    } else if (lowerName.endsWith(".md") || lowerName.endsWith(".markdown")) {
      parsed = parseMarkdownBook(content, file.name);
    } else {
      try {
        parsed = JSON.parse(content);
      } catch (_error) {
        parsed = parseMarkdownBook(content, file.name);
      }
    }

    upsertBook(parsed);
    renderShelf();
    renderReader();
    alert(`导入成功：${parsed.title || "未命名小说"}`);
  } catch (error) {
    alert(`导入失败：${error.message}`);
  } finally {
    event.target.value = "";
  }
}

function stripMarkdownLine(line) {
  let text = decodeHtmlEntities(String(line || "")).trim();
  if (!text) {
    return "";
  }
  if (/^\s{0,3}#{1,6}\s+/.test(text)) {
    text = text.replace(/^\s{0,3}#{1,6}\s+/, "");
  }
  text = text.replace(/^\s{0,3}>\s?/, "");
  text = text.replace(/^\s*[-*+]\s+/, "");
  text = text.replace(/^\s*\d+[.)、]\s+/, "");
  text = text.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  text = text.replace(/<[^>]+>/g, "");
  text = text.replace(/\*\*/g, "").replace(/__/g, "").replace(/~~/g, "").replace(/`/g, "");
  return decodeHtmlEntities(text).trim();
}

function parseMarkdownBook(content, fileName) {
  const lines = content
    .replace(/\ufeff/g, "")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => decodeHtmlEntities(line));
  const headingRegex = /^\s{0,3}(#{1,6})\s+(.*?)\s*$/;
  const chapterRegex = /(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*[章节组]|chapter\s*[-#:：]?\s*\d+|\bch\s*[-#:：]?\s*\d+)/i;

  const headings = [];
  lines.forEach((line, index) => {
    const match = line.match(headingRegex);
    if (!match) {
      return;
    }
    headings.push({
      line: index,
      level: match[1].length,
      title: decodeHtmlEntities(match[2]).trim()
    });
  });

  let chapterHeadings = headings.filter((item) => chapterRegex.test(item.title));
  if (chapterHeadings.length === 0) {
    chapterHeadings = lines
      .map((line, index) => ({ line: index, title: decodeHtmlEntities(line).trim() }))
      .filter((item) => item.title && chapterRegex.test(item.title));
  }

  const firstH1 = headings.find((item) => item.level === 1 && !chapterRegex.test(item.title));
  const plainTitle = fileName.replace(/\.[^.]+$/, "");
  const firstContentLine = lines.find((line) => line.trim());
  const bookTitle = firstH1
    ? firstH1.title
    : firstContentLine && !chapterRegex.test(firstContentLine)
      ? stripMarkdownLine(firstContentLine)
      : decodeHtmlEntities(plainTitle);

  if (chapterHeadings.length === 0) {
    const cleaned = [];
    let lastBlank = false;
    lines.forEach((line) => {
      const plain = stripMarkdownLine(line);
      if (!plain) {
        if (!lastBlank) {
          cleaned.push("");
          lastBlank = true;
        }
        return;
      }
      cleaned.push(plain);
      lastBlank = false;
    });
    const body = cleaned.join("\n").trim();
    if (!body) {
      throw new Error("Markdown 正文为空。");
    }
    return {
      id: `md-${Date.now()}`,
      title: bookTitle,
      description: `Markdown 导入：${fileName}`,
      wordGoal: 3500,
      chapters: [
        {
          title: "Chapter 1",
          english: body,
          chinese: /[\u4e00-\u9fff]/.test(body) ? body : "",
          targetWords: [],
        },
      ],
    };
  }

  const chapters = chapterHeadings
    .map((heading, index) => {
      const start = heading.line + 1;
      const end = index < chapterHeadings.length - 1 ? chapterHeadings[index + 1].line : lines.length;
      const bodyLines = lines.slice(start, end);
      const cleaned = [];
      let lastBlank = false;

      bodyLines.forEach((line) => {
        const trimmed = line.trim();
        if (/^[=\-_*]{3,}$/.test(trimmed)) {
          return;
        }

        const h = line.match(headingRegex);
        if (h && !chapterRegex.test(h[2].trim())) {
          if (h[2].trim()) {
            cleaned.push(stripMarkdownLine(h[2]));
            lastBlank = false;
          }
          return;
        }

        if (!trimmed) {
          if (!lastBlank) {
            cleaned.push("");
            lastBlank = true;
          }
          return;
        }

        if (/^[（(【\[]?\s*第?.{0,20}章完\s*[】\])）)]?$/.test(trimmed)) {
          return;
        }

        const plain = stripMarkdownLine(line);
        if (!plain) {
          return;
        }
        cleaned.push(plain);
        lastBlank = false;
      });

      const body = cleaned.join("\n").trim();
      if (!body) {
        return null;
      }

      return {
        title: stripMarkdownLine(heading.title) || `Chapter ${index + 1}`,
        english: body,
        chinese: /[\u4e00-\u9fff]/.test(body) ? body : "",
        targetWords: []
      };
    })
    .filter(Boolean);

  if (chapters.length === 0) {
    throw new Error("Markdown 章节内容为空。");
  }

  return {
    id: `md-${Date.now()}`,
    title: bookTitle,
    description: `Markdown 导入：${fileName}`,
    wordGoal: 3500,
    chapters
  };
}

function shuffle(arr) {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

async function enterFocusMode() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    }
  } catch (_error) {
    // 部分 iOS 浏览器不支持 Fullscreen API
  }
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (_error) {
    // 不支持时忽略
  }
}

function escapeAttr(input) {
  return escapeHtml(input).replace(/`/g, "&#96;");
}

function escapeHtml(input) {
  return String(input)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

window.addEventListener("beforeunload", () => {
  if (wakeLock) {
    wakeLock.release();
  }
});

init();
