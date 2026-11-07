const DEFAULT_CONFIG = {
  connection: {
    api_key: "",
    api_base: "https://api.mosi.cn",
    proxy: "",
    timeout: 120,
  },
  tts: {
    model: "moss-tts-1.5-flash",
    voice_id: "",
    language: "",
    response_format: "mp3",
    max_chars: 5000,
  },
  stt: {
    model: "moss-transcribe-1.0",
    diarize: true,
    keyterms: [],
    include_speaker: true,
    include_timestamp: false,
    max_upload_mb: 100,
  },
  routing: {
    auto_sync: true,
    auto_enable: true,
    tts_provider_id: "moss_tts",
    stt_provider_id: "moss_stt",
  },
};

const TTS_MODELS = [
  ["moss-tts-1.5-flash", "1.5 Flash · 快"],
  ["moss-tts-1.0-pro", "1.0 Pro · 稳"],
  ["moss-tts-1.5-flash-2026-06-26", "1.5 Flash 快照"],
  ["moss-tts-1.0-pro-2026-02-07", "1.0 Pro 快照"],
];

const STT_MODELS = [
  ["moss-transcribe-1.0", "Transcribe 1.0"],
  ["moss-transcribe-diarize-pro", "Diarize Pro · 多说话人"],
  ["moss-transcribe-1.0-2026-07-22", "Transcribe 1.0 快照"],
  ["moss-transcribe-diarize-pro-2026-07-03", "Diarize Pro 快照"],
];

const LANGUAGES = [
  ["", "自动判断"],
  ["Chinese", "中文"],
  ["Cantonese", "粤语"],
  ["English", "英语"],
  ["Japanese", "日语"],
  ["Korean", "韩语"],
  ["French", "法语"],
  ["German", "德语"],
  ["Spanish", "西班牙语"],
  ["Portuguese", "葡萄牙语"],
  ["Italian", "意大利语"],
  ["Russian", "俄语"],
  ["Arabic", "阿拉伯语"],
  ["Hindi", "印地语"],
  ["Thai", "泰语"],
  ["Vietnamese", "越南语"],
  ["Turkish", "土耳其语"],
  ["Polish", "波兰语"],
  ["Dutch", "荷兰语"],
  ["Swedish", "瑞典语"],
  ["Danish", "丹麦语"],
  ["Finnish", "芬兰语"],
  ["Greek", "希腊语"],
  ["Hebrew", "希伯来语"],
  ["Hungarian", "匈牙利语"],
  ["Czech", "捷克语"],
  ["Romanian", "罗马尼亚语"],
  ["Malay", "马来语"],
  ["Tagalog", "他加禄语"],
  ["Swahili", "斯瓦希里语"],
  ["Macedonian", "马其顿语"],
  ["Persian", "波斯语"],
];

const FORMATS = [
  ["mp3", "mp3"],
  ["wav", "wav"],
];

const MODEL_LABELS = Object.fromEntries([...TTS_MODELS, ...STT_MODELS]);

const state = {
  config: null,
  draft: null,
  status: null,
  voices: [],
  voiceSource: "none",
  voiceNotice: "",
  voiceLoading: false,
  dirty: false,
  saving: false,
  picks: {},
  tts: { audio: null, fileName: "" },
  stt: { file: null },
};

const $ = (id) => document.getElementById(id);
const busyLabels = new WeakMap();

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 20 ? `${text.slice(0, 10)}…${text.slice(-6)}` : text;
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatClock(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  return `${String(minutes).padStart(2, "0")}:${String(Math.floor(value % 60)).padStart(2, "0")}`;
}

function modelLabel(model) {
  return MODEL_LABELS[model] || model || "—";
}

function getBridge() {
  return window.AstrBotPluginView || window.AstrBotPluginPage || null;
}

function toast(message, kind = "info") {
  const element = $("toast");
  element.textContent = message;
  element.className = `toast is-show${kind === "ok" ? " is-ok" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    element.className = "toast";
  }, 4800);
}

function setInlineError(id, message) {
  const element = $(id);
  element.textContent = message || "";
  element.hidden = !message;
}

function clearInlineError(id) {
  setInlineError(id, "");
}

function setBusy(button, busy, label = "处理中…") {
  if (!button) return;
  if (busy) {
    if (!busyLabels.has(button)) busyLabels.set(button, button.innerHTML);
    button.disabled = true;
    button.textContent = label;
  } else {
    button.disabled = false;
    if (busyLabels.has(button)) {
      button.innerHTML = busyLabels.get(button);
      busyLabels.delete(button);
    }
  }
}

async function apiGet(endpoint, params) {
  const bridge = getBridge();
  if (!bridge) throw new Error("页面桥接未加载");
  return bridge.apiGet(endpoint, params || {});
}

async function apiPost(endpoint, body) {
  const bridge = getBridge();
  if (!bridge) throw new Error("页面桥接未加载");
  return bridge.apiPost(endpoint, body || {});
}

function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

async function fileToBase64(file) {
  const dataUrl = await fileToDataURL(file);
  return dataUrl.split(",", 2)[1] || "";
}

function parseKeyterms(value) {
  return String(value || "")
    .replaceAll("，", ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 50);
}

/* ---------------------------------------------------------------- custom pick */

function closePicks(except) {
  document.querySelectorAll(".pick.is-open").forEach((pick) => {
    if (pick !== except) {
      pick.classList.remove("is-open");
      pick.querySelector(".pick-menu").hidden = true;
      pick.querySelector(".pick-btn").setAttribute("aria-expanded", "false");
    }
  });
}

function setPick(id, value) {
  const pick = $(id);
  if (!pick) return;
  const options = pick._options || [];
  const found = options.find(([key]) => String(key) === String(value));
  pick.dataset.value = found ? found[0] : String(value ?? "");
  pick.querySelector(".pick-value").textContent = found ? found[1] : (value || "—");
  pick.querySelectorAll(".pick-option").forEach((option) => {
    option.classList.toggle("is-selected", option.dataset.value === pick.dataset.value);
  });
}

function getPick(id) {
  return $(id)?.dataset.value || "";
}

function setPickEnabled(id, enabled) {
  const pick = $(id);
  if (!pick) return;
  pick.querySelector(".pick-btn").disabled = !enabled;
  pick.classList.toggle("is-disabled", !enabled);
}

function createPick(id, options, onSelect) {
  const pick = $(id);
  const button = pick.querySelector(".pick-btn");
  const menu = pick.querySelector(".pick-menu");
  pick._options = options;
  menu.innerHTML = options
    .map(([value, label]) => `<button class="pick-option" type="button" role="option" data-value="${esc(value)}">${esc(label)}</button>`)
    .join("");
  menu.addEventListener("click", (event) => {
    const option = event.target.closest(".pick-option");
    if (!option) return;
    setPick(id, option.dataset.value);
    pick.classList.remove("is-open");
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    onSelect?.(option.dataset.value);
  });
  button.addEventListener("click", () => {
    const open = !pick.classList.contains("is-open");
    closePicks(pick);
    pick.classList.toggle("is-open", open);
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  });
}

/* ---------------------------------------------------------------- voice list */

function voiceLabel(voice) {
  return voice.name ? `${voice.name} · ${shortId(voice.id)}` : shortId(voice.id);
}

function renderVoiceMenu() {
  const options = $("voice-options");
  const note = $("voice-note");
  if (!options || !note) return;
  const query = $("voice-search").value.trim().toLowerCase();
  const filtered = state.voices.filter((voice) => {
    if (!query) return true;
    return `${voice.name || ""} ${voice.id}`.toLowerCase().includes(query);
  });
  if (state.voiceLoading) {
    options.innerHTML = `<div class="voice-menu-foot">正在读取账号音色…</div>`;
  } else if (!filtered.length) {
    options.innerHTML = "";
  } else {
    options.innerHTML = filtered
      .map(
        (voice) => `
          <button class="voice-option" type="button" data-voice-id="${esc(voice.id)}">
            <span class="voice-option-name">${esc(voice.name || "未命名音色")}</span>
            <span class="voice-option-id">${esc(voice.id)}</span>
          </button>`,
      )
      .join("");
  }
  let text = state.voiceNotice || "";
  if (!text) {
    if (!state.voices.length) {
      text = state.config?._meta?.api_key_configured
        ? "账号下没有可用音色。到 MOSS Create 克隆后复制 voice_id。"
        : "先保存 API Key，才能读取账号音色。";
    } else {
      text = `${state.voices.length} 个账号音色 · 来源 MOSS`;
    }
  }
  note.textContent = text;
}

async function loadVoices(force = false) {
  if (state.voiceLoading) return;
  state.voiceLoading = true;
  renderVoiceMenu();
  try {
    const response = await apiGet("page/voices");
    state.voices = Array.isArray(response.voices) ? response.voices : [];
    state.voiceSource = response.source || "none";
    state.voiceNotice = response.notice || response.error || "";
    if (force && state.voiceNotice) toast(state.voiceNotice, response.error ? "err" : "info");
  } catch (error) {
    state.voices = [];
    state.voiceSource = "error";
    state.voiceNotice = `读取账号音色失败：${error.message || error}`;
    if (force) toast(state.voiceNotice, "err");
  } finally {
    state.voiceLoading = false;
    renderVoiceMenu();
  }
}

function openVoiceMenu() {
  $("voice-menu").hidden = false;
  $("voice-box").classList.add("is-open");
  renderVoiceMenu();
}

function closeVoiceMenu() {
  $("voice-menu").hidden = true;
  $("voice-box").classList.remove("is-open");
}

function chooseVoice(voiceId) {
  $("voice-id").value = voiceId;
  closeVoiceMenu();
  markDirty();
}

/* ---------------------------------------------------------------- config/render */

function fillControls() {
  const draft = state.draft || DEFAULT_CONFIG;
  $("api-key").value = draft.connection.api_key || "";
  $("api-base").value = draft.connection.api_base || "https://api.mosi.cn";
  $("api-proxy").value = draft.connection.proxy || "";
  $("api-timeout").value = draft.connection.timeout || 120;
  $("voice-id").value = draft.tts.voice_id || "";
  $("tts-max-chars").value = draft.tts.max_chars || 5000;
  $("stt-keyterms").value = (draft.stt.keyterms || []).join(", ");
  $("stt-max-mb").value = draft.stt.max_upload_mb || 100;
  $("stt-diarize").checked = Boolean(draft.stt.diarize);
  $("stt-speaker").checked = Boolean(draft.stt.include_speaker);
  $("stt-timestamp").checked = Boolean(draft.stt.include_timestamp);
  $("routing-auto-sync").checked = Boolean(draft.routing.auto_sync);
  $("routing-auto-enable").checked = Boolean(draft.routing.auto_enable);
  $("provider-tts-id").textContent = draft.routing.tts_provider_id || "moss_tts";
  $("provider-stt-id").textContent = draft.routing.stt_provider_id || "moss_stt";
  setPick("pick-tts-model", draft.tts.model);
  setPick("pick-language", draft.tts.language);
  setPick("pick-format", draft.tts.response_format);
  setPick("pick-stt-model", draft.stt.model);
  $("api-key").placeholder =
    draft._meta?.api_key_source === "env"
      ? "来自环境变量 MOSS_API_KEY，留空继续使用"
      : "sk-... 或留空使用 MOSS_API_KEY";
  updateTtsAvailability();
  updateSttAvailability();
}

function applyConfig(config) {
  state.config = config || clone(DEFAULT_CONFIG);
  state.draft = clone(state.config);
  fillControls();
  updateDirty(false);
  renderVoiceMenu();
}

function collectDraft() {
  const draft = clone(state.draft || state.config || DEFAULT_CONFIG);
  draft.connection = draft.connection || {};
  draft.tts = draft.tts || {};
  draft.stt = draft.stt || {};
  draft.routing = draft.routing || {};
  draft.connection.api_key = $("api-key").value.trim();
  draft.connection.api_base = $("api-base").value.trim() || "https://api.mosi.cn";
  draft.connection.proxy = $("api-proxy").value.trim();
  draft.connection.timeout = Number($("api-timeout").value) || 120;
  draft.tts.model = getPick("pick-tts-model") || draft.tts.model;
  draft.tts.voice_id = $("voice-id").value.trim();
  draft.tts.language = getPick("pick-language");
  draft.tts.response_format = getPick("pick-format") || "mp3";
  draft.tts.max_chars = Number($("tts-max-chars").value) || 5000;
  draft.stt.model = getPick("pick-stt-model") || draft.stt.model;
  draft.stt.keyterms = parseKeyterms($("stt-keyterms").value);
  draft.stt.max_upload_mb = Number($("stt-max-mb").value) || 100;
  draft.stt.diarize = $("stt-diarize").checked;
  draft.stt.include_speaker = $("stt-speaker").checked;
  draft.stt.include_timestamp = $("stt-timestamp").checked;
  draft.routing.auto_sync = $("routing-auto-sync").checked;
  draft.routing.auto_enable = $("routing-auto-enable").checked;
  return draft;
}

function markDirty() {
  state.draft = collectDraft();
  updateTtsAvailability();
  updateSttAvailability();
  updateDirty(true);
}

function updateDirty(dirty) {
  state.dirty = Boolean(dirty);
  $("btn-save").hidden = !state.dirty;
  $("save-note").textContent = state.dirty ? "未保存" : "";
}

function updateTtsAvailability() {
  const model = getPick("pick-tts-model");
  const flash = String(model).startsWith("moss-tts-1.5");
  setPickEnabled("pick-language", flash);
}

function updateSttAvailability() {
  const model = getPick("pick-stt-model");
  const diarizeModel = String(model).includes("diarize");
  $("stt-diarize").disabled = !diarizeModel;
  $("stt-keyterms").disabled = !diarizeModel;
  $("stt-keyterms").title = diarizeModel ? "" : "只有 Diarize Pro 支持关键词";
}

function providerStateText(provider) {
  if (!provider) return "不可用";
  if (!provider.exists) return "未创建";
  if (provider.loaded && provider.selected && provider.routing_enabled) return "已启用";
  if (provider.loaded) return "已加载 · 未选中";
  if (provider.exists) return "已创建 · 未加载";
  return "未创建";
}

function providerStateClass(provider) {
  if (!provider) return "is-err";
  if (!provider.exists) return "is-err";
  return provider.loaded && provider.selected && provider.routing_enabled ? "is-on" : "is-warn";
}

function applyStatus(payload) {
  const providers = payload?.providers || payload || {};
  state.status = providers;
  const meta = state.config?._meta || payload?.config?._meta || {};
  const keyConfigured = Boolean(meta.api_key_configured || providers.api_key_configured);
  const keySource = meta.api_key_source || providers.api_key_source || "none";
  const masked = meta.api_key_masked || "";

  $("led-api").className = `led ${keyConfigured ? "is-on" : "is-err"}`;
  $("status-api").textContent = keyConfigured
    ? `API 已配置${masked ? ` · ${masked}` : ""}`
    : "API 未配置";

  const tts = providers.tts || {};
  const stt = providers.stt || {};
  if (!keyConfigured) {
    $("led-tts").className = "led is-warn";
    $("status-tts").textContent = "等待 API Key";
    $("led-stt").className = "led is-warn";
    $("status-stt").textContent = "等待 API Key";
  } else {
    $("led-tts").className = `led ${tts.selected && tts.routing_enabled ? "is-on" : tts.exists ? "is-warn" : "is-err"}`;
    $("status-tts").textContent = tts.selected && tts.routing_enabled
      ? "TTS 已接入"
      : tts.exists
        ? "TTS 待切换"
        : "TTS 未接入";
    $("led-stt").className = `led ${stt.selected && stt.routing_enabled ? "is-on" : stt.exists ? "is-warn" : "is-err"}`;
    $("status-stt").textContent = stt.selected && stt.routing_enabled
      ? "STT 已接入"
      : stt.exists
        ? "STT 待切换"
        : "STT 未接入";
  }

  if (!keyConfigured) {
    $("provider-tts-state").textContent = "缺 API Key";
    $("provider-tts-state").className = "provider-state is-warn";
    $("provider-stt-state").textContent = "缺 API Key";
    $("provider-stt-state").className = "provider-state is-warn";
    $("routing-tag").textContent = "NO KEY";
  } else {
    $("provider-tts-state").textContent = providerStateText(tts);
    $("provider-tts-state").className = `provider-state ${providerStateClass(tts)}`;
    $("provider-stt-state").textContent = providerStateText(stt);
    $("provider-stt-state").className = `provider-state ${providerStateClass(stt)}`;
    $("routing-tag").textContent =
      tts.selected && tts.routing_enabled && stt.selected && stt.routing_enabled
        ? "ACTIVE"
        : tts.exists || stt.exists
          ? "READY"
          : "IDLE";
  }
  $("key-tag").textContent = keySource === "env" ? "ENV" : keyConfigured ? "CONFIG" : "MISSING";
}

/* ---------------------------------------------------------------- load/save */

async function loadAll(options = {}) {
  const force = Boolean(options.force);
  if (state.dirty && force) {
    toast("有未保存的更改，先保存再刷新。", "err");
    return;
  }
  try {
    const config = await apiGet("page/config");
    applyConfig(config.config || DEFAULT_CONFIG);
  } catch (error) {
    applyConfig(DEFAULT_CONFIG);
    toast(`读取配置失败：${error.message || error}`, "err");
  }
  try {
    const status = await apiGet("page/status");
    applyStatus(status);
  } catch (error) {
    applyStatus({});
    toast(`读取状态失败：${error.message || error}`, "err");
  }
  if (state.config?._meta?.api_key_configured) {
    void loadVoices(false);
  } else {
    state.voices = [];
    state.voiceNotice = "先保存 API Key，才能读取账号音色。";
    renderVoiceMenu();
  }
}

async function saveConfig(options = {}) {
  if (state.saving) return false;
  const silent = Boolean(options.silent);
  const draft = collectDraft();
  if (!/^https?:\/\//i.test(draft.connection.api_base)) {
    toast("API 地址必须以 http:// 或 https:// 开头。", "err");
    return false;
  }
  state.saving = true;
  setBusy($("btn-save"), true, "保存中…");
  setBusy($("btn-save-routing"), true, "保存中…");
  try {
    const response = await apiPost("page/config", { config: draft });
    applyConfig(response.config || draft);
    if (response.providers) applyStatus({ providers: response.providers });
    if (draft.connection.api_key) void loadVoices(false);
    const synced = response.synced;
    if (!silent) {
      if (synced && synced.ok) {
        toast("配置已保存，Provider 已同步。", "ok");
      } else if (synced && synced.error) {
        toast(`配置已保存；Provider 同步：${synced.error}`, "err");
      } else {
        toast("配置已保存。", "ok");
      }
    }
    return true;
  } catch (error) {
    toast(`保存失败：${error.message || error}`, "err");
    return false;
  } finally {
    state.saving = false;
    setBusy($("btn-save"), false);
    setBusy($("btn-save-routing"), false);
  }
}

async function syncProviders() {
  if (state.dirty) {
    const saved = await saveConfig({ silent: true });
    if (!saved) return;
  }
  setBusy($("btn-sync"), true, "写入中…");
  try {
    const response = await apiPost("page/sync", {});
    if (response.providers) applyStatus({ providers: response.providers });
    if (response.ok) {
      toast("已写入 AstrBot，MOSS 语音链路就绪。", "ok");
    } else {
      toast(response.error || "Provider 同步未完成，请检查日志。", "err");
    }
  } catch (error) {
    toast(`同步失败：${error.message || error}`, "err");
  } finally {
    setBusy($("btn-sync"), false);
  }
}

async function testConnection() {
  setInlineError("tts-error", "");
  $("test-result").textContent = "连接中…";
  setBusy($("btn-test"), true, "测试中…");
  try {
    const response = await apiPost("page/test", {
      connection: {
        api_key: $("api-key").value.trim(),
        api_base: $("api-base").value.trim() || "https://api.mosi.cn",
        proxy: $("api-proxy").value.trim(),
        timeout: Number($("api-timeout").value) || 120,
      },
    });
    const sample = response.sample_voice?.name ? ` · ${response.sample_voice.name}` : "";
    $("test-result").textContent = `连接正常 · ${response.latency_ms} ms${sample}`;
    toast("API Key 可用。", "ok");
  } catch (error) {
    $("test-result").textContent = `失败 · ${error.message || error}`;
    toast(`连接失败：${error.message || error}`, "err");
  } finally {
    setBusy($("btn-test"), false);
  }
}

/* ---------------------------------------------------------------- test TTS */

function setupAudio(dataUrl, meta) {
  const audio = $("audio");
  audio.pause();
  audio.src = dataUrl;
  state.tts.audio = audio;
  state.tts.fileName = `moss-tts-test.${meta.format || "mp3"}`;
  $("mini-player").hidden = false;
  $("tts-download").href = dataUrl;
  $("tts-download").download = state.tts.fileName;
  $("mini-meta").textContent = [
    modelLabel(meta.model),
    shortId(meta.voice_id),
    formatBytes(meta.bytes),
    `${(Number(meta.elapsed_ms || 0) / 1000).toFixed(1)}s`,
  ].join(" · ");
  $("mini-clock").textContent = "00:00";
  $("btn-play").classList.remove("is-playing");
  audio.load();
}

function togglePlay() {
  const audio = state.tts.audio || $("audio");
  if (!audio?.src) return;
  if (audio.paused) {
    audio.play().catch((error) => toast(`播放失败：${error.message || error}`, "err"));
  } else {
    audio.pause();
  }
}

function updatePlayState() {
  const audio = $("audio");
  const playing = Boolean(audio && !audio.paused);
  $("btn-play").classList.toggle("is-playing", playing);
  $("btn-play").setAttribute("aria-label", playing ? "暂停" : "播放");
  $("mini-clock").textContent = formatClock(audio.currentTime);
}

async function doTestTTS() {
  const text = $("test-text").value.trim();
  const draft = collectDraft();
  state.draft = draft;
  if (!text) {
    setInlineError("tts-error", "先写一段测试文本。");
    return;
  }
  if (!draft.tts.voice_id) {
    setInlineError("tts-error", "先填音色 ID，或从账号音色里选一个。");
    return;
  }
  clearInlineError("tts-error");
  setBusy($("btn-test-tts"), true, "合成中…");
  $("tts-result").textContent = "";
  try {
    const response = await apiPost("page/tts", {
      text,
      model: draft.tts.model,
      voice_id: draft.tts.voice_id,
      language: draft.tts.language,
      format: draft.tts.response_format,
    });
    setupAudio(`data:${response.mime};base64,${response.audio_base64}`, response);
    $("tts-result").textContent = `${response.elapsed_ms} ms`;
  } catch (error) {
    setInlineError("tts-error", error.message || String(error));
  } finally {
    setBusy($("btn-test-tts"), false);
  }
}

/* ---------------------------------------------------------------- test STT */

function setAudioFile(file) {
  if (!file) return;
  const maxMb = Number(state.draft?.stt?.max_upload_mb) || 100;
  if (file.size > maxMb * 1024 * 1024) {
    setInlineError("stt-error", `文件 ${formatBytes(file.size)}，超过 ${maxMb} MB 上限。`);
    return;
  }
  clearInlineError("stt-error");
  state.stt.file = file;
  $("file-name").textContent = `${file.name} · ${formatBytes(file.size)}`;
}

async function doTestSTT() {
  if (!state.stt.file) {
    setInlineError("stt-error", "先选择一个音频文件。");
    return;
  }
  const draft = collectDraft();
  state.draft = draft;
  const file = state.stt.file;
  clearInlineError("stt-error");
  $("stt-result").hidden = true;
  setBusy($("btn-test-stt"), true, "转写中…");
  $("stt-result-state").textContent = "";
  try {
    let response;
    if (file.size <= 8 * 1024 * 1024) {
      const data = await fileToBase64(file);
      response = await apiPost("page/stt", {
        filename: file.name || "audio",
        content_type: file.type || "",
        data,
        model: draft.stt.model,
        diarize: draft.stt.diarize,
        keyterms: draft.stt.keyterms,
        include_speaker: draft.stt.include_speaker,
        include_timestamp: draft.stt.include_timestamp,
      });
    } else {
      const bridge = getBridge();
      if (!bridge?.upload) throw new Error("当前 AstrBot 版本不支持页面大文件上传。");
      if (state.dirty) toast("大文件会使用已保存的转写设置。", "info");
      response = await bridge.upload("page/stt", file);
    }
    $("stt-text").textContent = response.text || "";
    $("stt-result").hidden = false;
    $("stt-result-state").textContent = [
      modelLabel(response.model),
      `${(Number(response.elapsed_ms || 0) / 1000).toFixed(1)}s`,
    ].join(" · ");
  } catch (error) {
    setInlineError("stt-error", error.message || String(error));
  } finally {
    setBusy($("btn-test-stt"), false);
  }
}

async function copyTranscript() {
  const text = $("stt-text").textContent || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制转写文本。", "ok");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast("已复制转写文本。", "ok");
  }
}

/* ---------------------------------------------------------------- events */

function bindEvents() {
  $("btn-refresh").addEventListener("click", () => void loadAll({ force: true }));
  $("btn-save").addEventListener("click", () => void saveConfig());
  $("btn-save-routing").addEventListener("click", () => void saveConfig());
  $("btn-sync").addEventListener("click", () => void syncProviders());
  $("btn-test").addEventListener("click", () => void testConnection());
  $("btn-test-tts").addEventListener("click", () => void doTestTTS());
  $("btn-test-stt").addEventListener("click", () => void doTestSTT());
  $("btn-copy").addEventListener("click", () => void copyTranscript());
  $("btn-play").addEventListener("click", togglePlay);
  $("btn-file").addEventListener("click", () => $("audio-file").click());
  $("audio-file").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) setAudioFile(file);
  });

  $("btn-reveal").addEventListener("click", () => {
    const input = $("api-key");
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    $("btn-reveal").textContent = visible ? "显示" : "隐藏";
  });

  $("btn-voices").addEventListener("click", async () => {
    await loadVoices(true);
    openVoiceMenu();
  });
  $("voice-id").addEventListener("focus", () => {
    if (state.voices.length) openVoiceMenu();
  });
  $("voice-id").addEventListener("input", () => {
    closeVoiceMenu();
    markDirty();
  });
  $("voice-search").addEventListener("input", renderVoiceMenu);
  $("voice-options").addEventListener("click", (event) => {
    const option = event.target.closest("[data-voice-id]");
    if (option) chooseVoice(option.dataset.voiceId);
  });
  $("voice-menu").addEventListener("click", (event) => event.stopPropagation());

  ["api-base", "api-proxy", "api-timeout", "tts-max-chars", "stt-max-mb"].forEach((id) => {
    $(id).addEventListener("change", markDirty);
  });
  $("api-key").addEventListener("input", markDirty);
  $("stt-keyterms").addEventListener("input", markDirty);
  ["stt-diarize", "stt-speaker", "stt-timestamp", "routing-auto-sync", "routing-auto-enable"].forEach((id) => {
    $(id).addEventListener("change", markDirty);
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".pick")) closePicks();
    if (!event.target.closest("#voice-box")) closeVoiceMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePicks();
      closeVoiceMenu();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.dirty) void saveConfig();
    }
  });

  const audio = $("audio");
  audio.addEventListener("play", updatePlayState);
  audio.addEventListener("pause", updatePlayState);
  audio.addEventListener("ended", updatePlayState);
  audio.addEventListener("timeupdate", updatePlayState);

  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

/* ---------------------------------------------------------------- boot */

async function boot() {
  createPick("pick-tts-model", TTS_MODELS, () => {
    updateTtsAvailability();
    markDirty();
  });
  createPick("pick-language", LANGUAGES, () => markDirty());
  createPick("pick-format", FORMATS, () => markDirty());
  createPick("pick-stt-model", STT_MODELS, () => {
    updateSttAvailability();
    markDirty();
  });
  bindEvents();
  applyConfig(DEFAULT_CONFIG);
  applyStatus({});

  const bridge = getBridge();
  if (!bridge) {
    $("led-api").className = "led is-err";
    $("status-api").textContent = "页面桥接未加载";
    toast("没有找到 AstrBotPluginView，请从 AstrBot 插件页打开。", "err");
    return;
  }
  try {
    const context = await Promise.race([
      bridge.ready(),
      new Promise((resolve) => window.setTimeout(() => resolve(null), 4000)),
    ]);
    if (context?.pageTitle) document.title = context.pageTitle;
    if (context) document.documentElement.dataset.theme = context.isDark ? "dark" : "light";
    bridge.onContext?.((next) => {
      if (next?.pageTitle) document.title = next.pageTitle;
      if (next) document.documentElement.dataset.theme = next.isDark ? "dark" : "light";
    });
  } catch {
    // 上下文只影响标题与主题。
  }
  await loadAll();
}

boot();
