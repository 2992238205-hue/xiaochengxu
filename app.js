const STORAGE_KEY = "english_reader_mvp_v2";
const PASS_RATE = 0.8;
const APP_CONFIG = window.APP_CONFIG || {};
const API_BASE = String(APP_CONFIG.apiBaseUrl || "").replace(/\/$/, "");
const SERVER_MODE = API_BASE.length > 0;
const USER_CAN_UPLOAD = SERVER_MODE ? Boolean(APP_CONFIG.userCanUpload) : true;
const TRANSLATION_CACHE_LIMIT = 1800;

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
    showChinese: false
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
  pendingChapterAdvance: false
};

const elements = {
  tabs: document.querySelectorAll(".tab-button"),
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
};

let speakingWord = "";
let wakeLock = null;
let longPressTimer = null;
let longPressTriggered = false;
let layoutRaf = 0;
const translationRequestCache = new Map();

async function init() {
  hydrateState();
  bindEvents();

  if (!USER_CAN_UPLOAD && elements.importCard) {
    elements.importCard.style.display = "none";
  }

  let loadedFromServer = false;
  if (SERVER_MODE) {
    loadedFromServer = await loadBooksFromServer();
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
  scheduleReaderLayoutMetrics();
  saveState();
}

function bindEvents() {
  elements.tabs.forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
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
  elements.showChinese.addEventListener("change", onReaderStyleChange);
  elements.startQuiz.addEventListener("click", beginQuiz);
  elements.speakWord.addEventListener("click", () => speakWord(speakingWord));

  elements.readingPanel.addEventListener("click", onReadingPanelClick);
  elements.readingPanel.addEventListener("pointerdown", onReadingPanelPointerDown);
  elements.readingPanel.addEventListener("pointerup", clearLongPressTimer);
  elements.readingPanel.addEventListener("pointerleave", clearLongPressTimer);
  elements.readingPanel.addEventListener("pointercancel", clearLongPressTimer);
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
      openCommentInput(state.commentContext.anchorId, state.commentContext.preview);
    }
  });

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
}

function decodeHtmlEntities(input) {
  if (input === null || input === undefined) {
    return "";
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(`<!doctype html><body>${String(input)}`, "text/html");
  return doc.body.textContent || "";
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
    const response = await fetch(`${API_BASE}/public/books`, { cache: "no-store" });
    if (!response.ok) {
      return false;
    }
    const data = await response.json();
    const incomingBooks = Array.isArray(data.books) ? data.books : [];
    state.books = incomingBooks.map((rawBook) => normalizeBook(rawBook));
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

      const english = decodeHtmlEntities(String(chapter.english || chapter.content || "")).trim();
      const chinese = decodeHtmlEntities(String(chapter.chinese || "")).trim();
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
    chapters: safeChapters
  };
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
    renderProfile();
  }
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

  state.books.forEach((book) => {
    ensureProgress(book.id);
    const progress = state.progressByBook[book.id];
    const item = document.createElement("article");
    item.className = "book-item";
    const chapterCount = book.chapters.length;
    const unlocked = Math.min(progress.unlockedChapter + 1, chapterCount);
    item.innerHTML = `
      <h3>${escapeHtml(book.title)}</h3>
      <p>${escapeHtml(book.description || "双语小说")}</p>
      <p>章节：${chapterCount} ｜ 已解锁：${unlocked}</p>
      <button data-open-book="${book.id}" class="primary-button">进入阅读</button>
    `;
    elements.bookshelfList.appendChild(item);
  });

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
}

function onReaderStyleChange() {
  state.settings.fontSize = Number(elements.fontSize.value);
  state.settings.lineHeight = Number(elements.lineHeight.value);
  state.settings.showChinese = Boolean(elements.showChinese.checked);
  state.cachedPagesKey = "";
  renderCurrentChapter();
  scheduleReaderLayoutMetrics();
  saveState();
}

function renderCurrentChapter() {
  const chapter = currentChapter();
  if (!chapter) {
    return;
  }

  elements.fontSize.value = String(state.settings.fontSize);
  elements.lineHeight.value = String(state.settings.lineHeight);
  elements.showChinese.checked = Boolean(state.settings.showChinese);
  elements.readerChapterTitle.textContent = chapter.title;

  const pagesKey = [
    state.activeBookId,
    state.activeChapterIndex,
    state.settings.fontSize,
    state.settings.lineHeight
  ].join(":");

  if (state.cachedPagesKey !== pagesKey) {
    state.pages = paginateChapter(chapter.english, state.settings.fontSize, state.settings.lineHeight);
    state.cachedPagesKey = pagesKey;
    state.activePageIndex = 0;
  }

  if (state.activePageIndex >= state.pages.length) {
    state.activePageIndex = state.pages.length - 1;
  }

  paintCurrentPage();
  updateGateStatus();
  hideTranslationCard();
}

function paginateChapter(text, fontSize, lineHeight) {
  const chunks = [];
  const normalized = text
    .replace(/\r/g, "")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  const joined = normalized.length > 0 ? normalized : [text];

  const scale = 20 / Math.max(16, fontSize);
  const lineScale = 1.7 / Math.max(1.4, lineHeight);
  const pageCharLimit = Math.max(320, Math.floor(1450 * scale * lineScale));

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

    const words = paragraph.split(/\s+/);
    let part = "";
    words.forEach((word) => {
      const candidate = `${part} ${word}`.trim();
      if (candidate.length > pageCharLimit) {
        chunks.push(part.trim());
        part = word;
      } else {
        part = candidate;
      }
    });
    if (part.trim()) {
      current = `${part}\n\n`;
    }
  });

  if (current.trim()) {
    chunks.push(current.trim());
  }

  return chunks.length > 0 ? chunks : [text];
}

function paintCurrentPage() {
  elements.readingPanel.classList.add("fade");
  const pageText = state.pages[state.activePageIndex] || "";
  const paragraphs = pageText
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  const html = paragraphs
    .map((paragraph, index) => {
      const anchorId = `p-${index}`;
      const anchorKey = buildAnchorKey(anchorId);
      const count = commentCount(anchorKey);
      const preview = paragraph.replace(/\s+/g, " ").slice(0, 36);
      const badgeClass = count > 0 ? "comment-badge" : "comment-badge hidden";
      return `<p class="paragraph" data-anchor-id="${anchorId}" data-anchor-preview="${escapeAttr(preview)}">${decorateWords(
        escapeHtml(paragraph)
      )}<button type="button" class="${badgeClass}" data-anchor-id="${anchorId}">${displayCommentCount(
        count
      )}</button></p>`;
    })
    .join("");

  setTimeout(() => {
    elements.readingPanel.style.fontSize = `${state.settings.fontSize}px`;
    elements.readingPanel.style.lineHeight = String(state.settings.lineHeight);
    elements.readingPanel.innerHTML = html || "<p class='hint'>本页暂无内容</p>";
    elements.readingPanel.classList.remove("fade");
    renderChinesePanel();
    scheduleReaderLayoutMetrics();
  }, 80);

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

  const chineseText = chapter.chinese ? escapeHtml(chapter.chinese).replace(/\n/g, "<br>") : "本章暂无中文对照";
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
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  if (target.closest(".comment-badge")) {
    const badge = target.closest(".comment-badge");
    const anchorId = badge?.dataset.anchorId;
    const paragraph = badge?.closest(".paragraph");
    if (anchorId) {
      openCommentList(anchorId, paragraph?.dataset.anchorPreview || "");
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
    if (!anchorId) {
      return;
    }
    openCommentInput(anchorId, paragraph.dataset.anchorPreview || "");
  }, 550);
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

function buildAnchorKey(anchorId) {
  return `${state.activeBookId}:${state.activeChapterIndex}:${state.activePageIndex}:${anchorId}`;
}

function commentCount(anchorKey) {
  return Array.isArray(state.commentsByAnchor[anchorKey]) ? state.commentsByAnchor[anchorKey].length : 0;
}

function displayCommentCount(count) {
  return String(Math.min(99, count));
}

function openCommentInput(anchorId, preview) {
  const anchorKey = buildAnchorKey(anchorId);
  state.commentContext = { anchorId, anchorKey, preview };
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
  paintCurrentPage();

  openCommentList(state.commentContext.anchorId, state.commentContext.preview);
}

function openCommentList(anchorId, preview) {
  const anchorKey = buildAnchorKey(anchorId);
  state.commentContext = { anchorId, anchorKey, preview };
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
    const maxPool = Math.min(words.length, 18);
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

    const questionCount = Math.min(8, resolvedWords.length);
    const selected = shuffle(resolvedWords).slice(0, questionCount);
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

function parseMarkdownBook(content, fileName) {
  const lines = content
    .replace(/\ufeff/g, "")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => decodeHtmlEntities(line));
  const headingRegex = /^\s{0,3}(#{1,6})\s+(.*?)\s*$/;
  const chapterRegex = /(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*章|Chapter\s*\d+)/i;

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

  const chapterHeadings = headings.filter((item) => chapterRegex.test(item.title));
  if (chapterHeadings.length === 0) {
    throw new Error("Markdown 中未识别到章节标题。请使用 # 第1章 / # Chapter 1 这样的标题格式。");
  }

  const firstH1 = headings.find((item) => item.level === 1 && !chapterRegex.test(item.title));
  const plainTitle = fileName.replace(/\.[^.]+$/, "");
  const bookTitle = firstH1 ? firstH1.title : decodeHtmlEntities(plainTitle);

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
            cleaned.push(decodeHtmlEntities(h[2]).trim());
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

        cleaned.push(decodeHtmlEntities(line));
        lastBlank = false;
      });

      const body = cleaned.join("\n").trim();
      if (!body) {
        return null;
      }

      return {
        title: heading.title,
        english: decodeHtmlEntities(body),
        chinese: /[\u4e00-\u9fff]/.test(body) ? decodeHtmlEntities(body) : "",
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
