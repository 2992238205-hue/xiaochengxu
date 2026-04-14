const API_BASE = String((window.APP_CONFIG && window.APP_CONFIG.apiBaseUrl) || "/api").replace(/\/$/, "");
const DEFAULT_AGENT_MODEL_MAP = `{
  "outline": "kimi-k2-thinking",
  "framework": "kimi-k2-0905-preview",
  "character": "kimi-k2-0905-preview",
  "scene": "kimi-k2-0905-preview",
  "deep_primary": "kimi-k2-thinking",
  "deep_secondary": "kimi-k2-0905-preview",
  "deep_referee": "kimi-k2-thinking",
  "writer": "kimi-k2-0905-preview",
  "qa": "kimi-k2-thinking",
  "chapter_logic_audit": "kimi-k2-thinking",
  "global_logic_audit": "kimi-k2-thinking",
  "deep_quality_audit": "kimi-k2-thinking",
  "rewrite": "kimi-k2-thinking"
}`;

const els = {
  adminKey: document.getElementById("admin-key"),
  moonshotApiKey: document.getElementById("moonshot-api-key"),
  moonshotModel: document.getElementById("moonshot-model"),
  moonshotBaseUrl: document.getElementById("moonshot-base-url"),
  moonshotTimeout: document.getElementById("moonshot-timeout"),
  thinkingMode: document.getElementById("thinking-mode"),
  moonshotTopP: document.getElementById("moonshot-top-p"),
  knowledgeQuery: document.getElementById("knowledge-query"),
  knowledgeTopK: document.getElementById("knowledge-top-k"),
  requireLLM: document.getElementById("require-llm"),
  allowTransientFallback: document.getElementById("allow-transient-fallback"),
  multiModelCollab: document.getElementById("multi-model-collab"),
  deepCommitteeModels: document.getElementById("deep-committee-models"),
  agentModelMapJson: document.getElementById("agent-model-map-json"),
  autoRewrite: document.getElementById("auto-rewrite"),
  maxRewriteRounds: document.getElementById("max-rewrite-rounds"),
  knowledgeTitle: document.getElementById("knowledge-title"),
  knowledgeTags: document.getElementById("knowledge-tags"),
  knowledgeSource: document.getElementById("knowledge-source"),
  knowledgeContent: document.getElementById("knowledge-content"),
  knowledgeAutoChunk: document.getElementById("knowledge-auto-chunk"),
  addKnowledge: document.getElementById("add-knowledge"),
  knowledgeList: document.getElementById("knowledge-list"),
  projectName: document.getElementById("project-name"),
  chapterIndex: document.getElementById("chapter-index"),
  totalChapters: document.getElementById("total-chapters"),
  targetWordCount: document.getElementById("target-word-count"),
  detailDensity: document.getElementById("detail-density"),
  writingStyle: document.getElementById("writing-style"),
  protagonistProfile: document.getElementById("protagonist-profile"),
  aiProfile: document.getElementById("ai-profile"),
  premise: document.getElementById("premise"),
  deepThinkingCard: document.getElementById("deep-thinking-card"),
  studentProfileJson: document.getElementById("student-profile-json"),
  fillStudentTemplate: document.getElementById("fill-student-template"),
  generateOutline: document.getElementById("generate-outline"),
  generateChapter: document.getElementById("generate-chapter"),
  statusLine: document.getElementById("status-line"),
  healthPill: document.getElementById("health-pill"),
  outlineOutput: document.getElementById("outline-output"),
  chapterOutput: document.getElementById("chapter-output"),
  routingOutput: document.getElementById("routing-output"),
  logicOutput: document.getElementById("logic-output"),
  stateOutput: document.getElementById("state-output"),
  agentOutput: document.getElementById("agent-output"),
  refreshHistory: document.getElementById("refresh-history"),
  historyList: document.getElementById("history-list"),
};

const state = {
  adminKey: localStorage.getItem("novel_studio_admin_key") || "",
  moonshotApiKey: localStorage.getItem("novel_studio_moonshot_api_key") || "",
  moonshotModel: localStorage.getItem("novel_studio_moonshot_model") || "kimi-k2-0905-preview",
  moonshotBaseUrl: localStorage.getItem("novel_studio_moonshot_base_url") || "https://api.moonshot.cn/v1",
  moonshotTimeout: localStorage.getItem("novel_studio_moonshot_timeout") || "90",
  thinkingMode: localStorage.getItem("novel_studio_thinking_mode") || "thinking",
  moonshotTopP: localStorage.getItem("novel_studio_moonshot_top_p") || "0.95",
  requireLLM: localStorage.getItem("novel_studio_require_llm") || "1",
  allowTransientFallback: localStorage.getItem("novel_studio_allow_transient_fallback") || "1",
  multiModelCollab: localStorage.getItem("novel_studio_multi_model_collab") || "1",
  deepCommitteeModels: localStorage.getItem("novel_studio_deep_committee_models") || "kimi-k2-thinking,kimi-k2-0905-preview",
  agentModelMapJson: localStorage.getItem("novel_studio_agent_model_map_json") || DEFAULT_AGENT_MODEL_MAP,
  targetWordCount: localStorage.getItem("novel_studio_target_word_count") || "3200",
  detailDensity: localStorage.getItem("novel_studio_detail_density") || "8",
  knowledgeItems: [],
  studentProfileTemplate: null,
};

function setStatus(text, isError = false) {
  els.statusLine.textContent = text;
  els.statusLine.style.color = isError ? "#b42318" : "";
}

function getAuthHeaders(includeJson = true) {
  const headers = {};
  if (includeJson) {
    headers["Content-Type"] = "application/json";
  }
  if (state.adminKey) {
    headers["X-Admin-Key"] = state.adminKey;
  }
  if (state.moonshotApiKey) {
    headers["X-Moonshot-Api-Key"] = state.moonshotApiKey;
  }
  if (state.moonshotModel) {
    headers["X-Moonshot-Model"] = state.moonshotModel;
  }
  if (state.moonshotBaseUrl) {
    headers["X-Moonshot-Base-Url"] = state.moonshotBaseUrl;
  }
  if (state.moonshotTimeout) {
    headers["X-Moonshot-Timeout"] = String(state.moonshotTimeout);
  }
  if (state.thinkingMode) {
    headers["X-Moonshot-Thinking-Mode"] = state.thinkingMode;
  }
  if (state.moonshotTopP) {
    headers["X-Moonshot-Top-P"] = String(state.moonshotTopP);
  }
  return headers;
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (err) {
    return String(value);
  }
}

function collectBasePayload() {
  let studentProfile = {};
  const rawStudentProfile = (els.studentProfileJson.value || "").trim();
  if (rawStudentProfile) {
    try {
      studentProfile = JSON.parse(rawStudentProfile);
    } catch (err) {
      studentProfile = { notes: rawStudentProfile };
    }
  }
  return {
    projectName: els.projectName.value.trim(),
    chapterIndex: Number(els.chapterIndex.value || 1),
    totalChapters: Number(els.totalChapters.value || 20),
    targetWordCount: Number(els.targetWordCount.value || 3200),
    detailDensity: Number(els.detailDensity.value || 8),
    writingStyle: els.writingStyle.value.trim(),
    protagonistProfile: els.protagonistProfile.value.trim(),
    aiProfile: els.aiProfile.value.trim(),
    premise: els.premise.value.trim(),
    deepThinkingCard: els.deepThinkingCard.value.trim(),
    studentProfile,
    knowledgeQuery: els.knowledgeQuery.value.trim(),
    knowledgeTopK: Number(els.knowledgeTopK.value || 6),
    requireLLM: Boolean(els.requireLLM.checked),
    allowTransientFallback: Boolean(els.allowTransientFallback.checked),
    multiModelCollab: Boolean(els.multiModelCollab.checked),
    autoRewrite: Boolean(els.autoRewrite.checked),
    maxRewriteRounds: Number(els.maxRewriteRounds.value || 2),
    moonshotModel: state.moonshotModel,
    moonshotBaseUrl: state.moonshotBaseUrl,
    moonshotTimeoutSeconds: Number(state.moonshotTimeout || 240),
    moonshotTopP: Number(state.moonshotTopP || 0.95),
    thinkingMode: state.thinkingMode || "thinking",
    deepCommitteeModels: String(els.deepCommitteeModels.value || "").trim(),
    agentModelMap: (() => {
      const raw = String(els.agentModelMapJson.value || "").trim();
      if (!raw) {
        return {};
      }
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (err) {
        throw new Error("Agent模型路由JSON格式错误");
      }
    })(),
  };
}

function parseErrorMessage(data, fallback) {
  if (!data) {
    return fallback;
  }
  if (typeof data.error === "string" && data.error) {
    return data.error;
  }
  return fallback;
}

function shortText(text, maxLen = 120) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (clean.length <= maxLen) {
    return clean;
  }
  return `${clean.slice(0, maxLen)}...`;
}

function renderKnowledgeList() {
  els.knowledgeList.innerHTML = "";
  if (state.knowledgeItems.length === 0) {
    els.knowledgeList.innerHTML = '<div class="list-item"><div class="list-item-meta">暂无知识条目</div></div>';
    return;
  }

  state.knowledgeItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "list-item";

    const head = document.createElement("div");
    head.className = "list-item-head";

    const title = document.createElement("div");
    title.className = "list-item-title";
    title.textContent = item.title || "未命名知识";

    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "删除";
    del.addEventListener("click", async () => {
      if (!confirm(`删除知识：${item.title || item.id} ?`)) {
        return;
      }
      await deleteKnowledge(item.id);
    });

    head.appendChild(title);
    head.appendChild(del);

    const meta = document.createElement("div");
    meta.className = "list-item-meta";
    meta.textContent = `tags: ${item.tags || "-"} | ${shortText(item.content || "", 80)}`;

    row.appendChild(head);
    row.appendChild(meta);
    els.knowledgeList.appendChild(row);
  });
}

function renderHistoryList(items) {
  els.historyList.innerHTML = "";
  if (!items || items.length === 0) {
    els.historyList.innerHTML = '<div class="list-item"><div class="list-item-meta">暂无历史章节</div></div>';
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "list-item";
    row.innerHTML = `
      <div class="list-item-head">
        <div class="list-item-title">${item.project_name || "-"} · 第${item.chapter_index}章</div>
        <div class="list-item-meta">质量 ${item.quality_score || 0}</div>
      </div>
      <div class="list-item-meta">${shortText(item.chapter_title || "-", 80)}</div>
      <div class="list-item-meta">${shortText(item.chapter_summary || "-", 160)}</div>
    `;
    els.historyList.appendChild(row);
  });
}

async function fetchHealth() {
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/health`, {
      headers: getAuthHeaders(false),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      els.healthPill.textContent = "模型状态异常";
      return;
    }
    els.healthPill.textContent = `${data.provider} · ${data.model}`;
  } catch (err) {
    els.healthPill.textContent = "后端未连接";
  }
}

async function fetchStudentProfileTemplate() {
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/student-profile-template`);
    const data = await resp.json();
    if (!resp.ok || !data.ok || !data.template) {
      return;
    }
    state.studentProfileTemplate = data.template;
    if (!els.studentProfileJson.value.trim()) {
      els.studentProfileJson.value = pretty(data.template);
    }
  } catch (err) {
    // ignore template load errors
  }
}

async function loadProjectState() {
  const projectName = els.projectName.value.trim();
  if (!projectName) {
    return;
  }
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/project-state?projectName=${encodeURIComponent(projectName)}`);
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      return;
    }
    const statePayload = data.state || {};
    if (statePayload && Object.keys(statePayload).length > 0) {
      els.stateOutput.textContent = pretty(statePayload);
    }
    const studentProfile = data.studentProfile || {};
    if (studentProfile && Object.keys(studentProfile).length > 0) {
      const currentRaw = (els.studentProfileJson.value || "").trim();
      if (!currentRaw) {
        els.studentProfileJson.value = pretty(studentProfile);
      }
    }
  } catch (err) {
    // ignore
  }
}

async function loadKnowledge() {
  try {
    const q = encodeURIComponent(els.knowledgeQuery.value.trim());
    const resp = await fetch(`${API_BASE}/novel-studio/knowledge?limit=120&q=${q}`);
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "加载知识失败"));
    }
    state.knowledgeItems = data.items || [];
    renderKnowledgeList();
  } catch (err) {
    setStatus(`加载知识失败：${err.message}`, true);
  }
}

async function addKnowledge() {
  const payload = {
    title: els.knowledgeTitle.value.trim(),
    tags: els.knowledgeTags.value.trim(),
    source: els.knowledgeSource.value.trim() || "manual",
    content: els.knowledgeContent.value.trim(),
    autoChunk: Boolean(els.knowledgeAutoChunk.checked),
  };
  if (!payload.content) {
    setStatus("知识内容不能为空", true);
    return;
  }
  setStatus("正在保存知识...");
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/knowledge`, {
      method: "POST",
      headers: getAuthHeaders(true),
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "保存失败"));
    }
    els.knowledgeContent.value = "";
    setStatus(`已保存 ${data.createdCount} 条知识`);
    await loadKnowledge();
  } catch (err) {
    setStatus(`保存失败：${err.message}`, true);
  }
}

async function deleteKnowledge(id) {
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/knowledge/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: getAuthHeaders(false),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "删除失败"));
    }
    setStatus("已删除");
    await loadKnowledge();
  } catch (err) {
    setStatus(`删除失败：${err.message}`, true);
  }
}

async function runOutline() {
  let payload;
  try {
    payload = collectBasePayload();
  } catch (err) {
    setStatus(err.message || "参数格式错误", true);
    return;
  }
  if (!payload.projectName || !payload.premise) {
    setStatus("项目名和故事前提必填", true);
    return;
  }

  setStatus("正在生成全书大纲...");
  els.generateOutline.disabled = true;
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/outline`, {
      method: "POST",
      headers: getAuthHeaders(true),
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "生成大纲失败"));
    }
    const warnings = (data.result && data.result.warnings) || [];
    els.outlineOutput.textContent = pretty(data.result && data.result.outline);
    els.routingOutput.textContent = pretty(data.result && data.result.routingStrategy);
    els.stateOutput.textContent = pretty((data.result && data.result.context && data.result.context.projectState) || {});
    els.agentOutput.textContent = pretty(data.result && data.result.agent);
    setStatus(warnings.length ? `大纲生成完成（有降级告警）` : "大纲生成完成");
  } catch (err) {
    setStatus(`大纲失败：${err.message}`, true);
  } finally {
    els.generateOutline.disabled = false;
  }
}

function chapterDisplayText(result) {
  const chapter = (result && result.chapter) || {};
  const quality = (result && result.quality) || {};
  const warnings = (result && result.warnings) || [];
  const chunks = [];
  if (warnings.length) {
    chunks.push(`警告：${warnings.join(" | ")}`);
  }
  chunks.push(`# ${chapter.chapter_title || "未命名章节"}`);
  chunks.push(`质量评分：${quality.score || 0} | 通过：${quality.passed ? "是" : "否"}`);
  chunks.push(`主角阶段：${chapter.hero_stage || "-"} | AI能力：${chapter.ai_capability_level || "-"}`);
  chunks.push(`能量变化：+${chapter.energy_gain || 0} => ${chapter.energy_after || 0}`);
  chunks.push(`\n摘要：\n${chapter.chapter_summary || "-"}`);
  chunks.push(`\n正文：\n${chapter.chapter_text || "-"}`);
  chunks.push(`\n钩子：\n${chapter.ending_hook || "-"}`);
  return chunks.join("\n");
}

function logicDisplayText(result) {
  const quality = (result && result.quality) || {};
  const logicChecks = (result && result.logicChecks) || {};
  const rewrites = (result && result.rewrites) || {};
  const modelMeta = (result && result.model) || {};
  const chapter = logicChecks.chapter || {};
  const global = logicChecks.global || {};
  const deep = logicChecks.deep || {};
  const rows = [];
  rows.push(`# 总审计`);
  rows.push(`通过：${quality.passed ? "是" : "否"} | 评分：${quality.score || 0}`);
  rows.push(`分项：${pretty((quality && quality.breakdown) || {})}`);
  if (quality.length_constraints) {
    rows.push(`字数：当前约${quality.effective_chars || 0}，下限${quality.length_constraints.min_required}，目标${quality.length_constraints.target}`);
  }
  rows.push(`\n# 自动改写`);
  rows.push(`开启：${rewrites.autoRewrite ? "是" : "否"} | 触发：${rewrites.triggered ? "是" : "否"} | 回合：${rewrites.completedRounds || 0}/${rewrites.maxRounds || 0}`);
  rows.push(`收敛：${rewrites.converged ? "是" : "否"}`);
  rows.push(`轨迹：${pretty(rewrites.trace || [])}`);
  rows.push(`\n# 章节连续性审计`);
  rows.push(`通过：${chapter.passed ? "是" : "否"} | 评分：${chapter.score || 0}`);
  rows.push(`问题：${pretty(chapter.issues || [])}`);
  rows.push(`矛盾：${pretty(chapter.contradictions || [])}`);
  rows.push(`\n# 全书连续性审计`);
  rows.push(`通过：${global.passed ? "是" : "否"} | 评分：${global.score || 0}`);
  rows.push(`问题：${pretty(global.issues || [])}`);
  rows.push(`风险：${pretty(global.unresolved_risks || [])}`);
  rows.push(`\n# 深度思考审计`);
  rows.push(`通过：${deep.passed ? "是" : "否"} | 评分：${deep.score || 0}`);
  rows.push(`问题：${pretty(deep.issues || [])}`);
  rows.push(`\n# 模型路由`);
  rows.push(`多模型协作：${modelMeta.multi_model_collab ? "是" : "否"}`);
  rows.push(`深度委员会：${pretty(modelMeta.deep_committee_models || [])}`);
  rows.push(`Agent模型映射：${pretty(modelMeta.agent_model_map || {})}`);
  return rows.join("\n");
}

async function runChapter() {
  let payload;
  try {
    payload = collectBasePayload();
  } catch (err) {
    setStatus(err.message || "参数格式错误", true);
    return;
  }
  if (!payload.projectName || !payload.premise) {
    setStatus("项目名和故事前提必填", true);
    return;
  }

  setStatus(`正在生成第 ${payload.chapterIndex} 章...`);
  els.generateChapter.disabled = true;
  try {
    const resp = await fetch(`${API_BASE}/novel-studio/generate`, {
      method: "POST",
      headers: getAuthHeaders(true),
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "生成章节失败"));
    }
    const result = data.result || {};
    els.chapterOutput.textContent = chapterDisplayText(result);
    els.routingOutput.textContent = pretty(result.routingStrategy || {});
    els.logicOutput.textContent = logicDisplayText(result);
    els.stateOutput.textContent = pretty((result.projectState && result.projectState.merged) || {});
    els.agentOutput.textContent = pretty(result.agents || {});
    setStatus(`章节完成，记录ID: ${data.recordId}`);
    await loadHistory();
  } catch (err) {
    setStatus(`章节失败：${err.message}`, true);
  } finally {
    els.generateChapter.disabled = false;
  }
}

async function loadHistory() {
  const projectName = encodeURIComponent(els.projectName.value.trim());
  const url = `${API_BASE}/novel-studio/chapters?projectName=${projectName}&limit=50`;
  try {
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(parseErrorMessage(data, "加载历史失败"));
    }
    renderHistoryList(data.items || []);
  } catch (err) {
    setStatus(`历史加载失败：${err.message}`, true);
  }
}

function bindEvents() {
  els.adminKey.value = state.adminKey;
  els.moonshotApiKey.value = state.moonshotApiKey;
  els.moonshotModel.value = state.moonshotModel;
  els.moonshotBaseUrl.value = state.moonshotBaseUrl;
  els.moonshotTimeout.value = state.moonshotTimeout;
  els.thinkingMode.value = state.thinkingMode;
  els.moonshotTopP.value = state.moonshotTopP;
  els.requireLLM.checked = state.requireLLM !== "0";
  els.allowTransientFallback.checked = state.allowTransientFallback !== "0";
  els.multiModelCollab.checked = state.multiModelCollab !== "0";
  els.deepCommitteeModels.value = state.deepCommitteeModels;
  els.agentModelMapJson.value = state.agentModelMapJson;
  els.targetWordCount.value = state.targetWordCount;
  els.detailDensity.value = state.detailDensity;

  els.adminKey.addEventListener("input", () => {
    state.adminKey = els.adminKey.value.trim();
    localStorage.setItem("novel_studio_admin_key", state.adminKey);
  });
  els.moonshotApiKey.addEventListener("input", async () => {
    state.moonshotApiKey = els.moonshotApiKey.value.trim();
    localStorage.setItem("novel_studio_moonshot_api_key", state.moonshotApiKey);
    await fetchHealth();
  });
  els.moonshotModel.addEventListener("input", async () => {
    state.moonshotModel = els.moonshotModel.value.trim() || "kimi-k2-0905-preview";
    localStorage.setItem("novel_studio_moonshot_model", state.moonshotModel);
    await fetchHealth();
  });
  els.moonshotBaseUrl.addEventListener("input", async () => {
    state.moonshotBaseUrl = els.moonshotBaseUrl.value.trim() || "https://api.moonshot.cn/v1";
    localStorage.setItem("novel_studio_moonshot_base_url", state.moonshotBaseUrl);
    await fetchHealth();
  });
  els.moonshotTimeout.addEventListener("input", async () => {
    state.moonshotTimeout = String(Number(els.moonshotTimeout.value || 240));
    localStorage.setItem("novel_studio_moonshot_timeout", state.moonshotTimeout);
    await fetchHealth();
  });
  els.thinkingMode.addEventListener("change", async () => {
    state.thinkingMode = els.thinkingMode.value || "thinking";
    localStorage.setItem("novel_studio_thinking_mode", state.thinkingMode);
    await fetchHealth();
  });
  els.moonshotTopP.addEventListener("input", async () => {
    const val = Number(els.moonshotTopP.value || 0.95);
    state.moonshotTopP = String(Math.max(0.1, Math.min(1, val)));
    localStorage.setItem("novel_studio_moonshot_top_p", state.moonshotTopP);
    await fetchHealth();
  });
  els.requireLLM.addEventListener("change", () => {
    state.requireLLM = els.requireLLM.checked ? "1" : "0";
    localStorage.setItem("novel_studio_require_llm", state.requireLLM);
  });
  els.allowTransientFallback.addEventListener("change", () => {
    state.allowTransientFallback = els.allowTransientFallback.checked ? "1" : "0";
    localStorage.setItem("novel_studio_allow_transient_fallback", state.allowTransientFallback);
  });
  els.multiModelCollab.addEventListener("change", () => {
    state.multiModelCollab = els.multiModelCollab.checked ? "1" : "0";
    localStorage.setItem("novel_studio_multi_model_collab", state.multiModelCollab);
  });
  els.deepCommitteeModels.addEventListener("input", () => {
    state.deepCommitteeModels = String(els.deepCommitteeModels.value || "").trim();
    localStorage.setItem("novel_studio_deep_committee_models", state.deepCommitteeModels);
  });
  els.agentModelMapJson.addEventListener("input", () => {
    state.agentModelMapJson = String(els.agentModelMapJson.value || "").trim();
    localStorage.setItem("novel_studio_agent_model_map_json", state.agentModelMapJson);
  });
  els.targetWordCount.addEventListener("input", () => {
    state.targetWordCount = String(Number(els.targetWordCount.value || 3200));
    localStorage.setItem("novel_studio_target_word_count", state.targetWordCount);
  });
  els.detailDensity.addEventListener("input", () => {
    state.detailDensity = String(Number(els.detailDensity.value || 8));
    localStorage.setItem("novel_studio_detail_density", state.detailDensity);
  });
  els.knowledgeQuery.addEventListener("change", loadKnowledge);
  els.projectName.addEventListener("change", async () => {
    await loadProjectState();
    await loadHistory();
  });
  els.addKnowledge.addEventListener("click", addKnowledge);
  els.fillStudentTemplate.addEventListener("click", () => {
    if (!state.studentProfileTemplate) {
      setStatus("画像模板尚未加载完成", true);
      return;
    }
    els.studentProfileJson.value = pretty(state.studentProfileTemplate);
    setStatus("已填入学生画像模板");
  });
  els.generateOutline.addEventListener("click", runOutline);
  els.generateChapter.addEventListener("click", runChapter);
  els.refreshHistory.addEventListener("click", loadHistory);
}

async function init() {
  bindEvents();
  await fetchHealth();
  await fetchStudentProfileTemplate();
  await loadKnowledge();
  await loadProjectState();
  await loadHistory();
}

init();
