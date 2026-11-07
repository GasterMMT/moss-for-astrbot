/* 仅用于本地页面预览的 AstrBotPluginView mock，不随插件加载。 */
(function () {
  const NO_KEY = new URLSearchParams(location.search).get("nokey") === "1";
  const CONFIG = {
    connection: {
      api_key: NO_KEY ? "" : "moss_demo_key_1234567890",
      api_base: "https://api.mosi.cn",
      proxy: "",
      timeout: 120,
    },
    tts: {
      model: "moss-tts-1.5-flash",
      voice_id: "806c9695-6160-404e-8722-4f788d935af3",
      language: "Chinese",
      response_format: "mp3",
      max_chars: 5000,
    },
    stt: {
      model: "moss-transcribe-diarize-pro",
      diarize: true,
      keyterms: ["MOSS", "AstrBot"],
      include_speaker: true,
      include_timestamp: true,
      max_upload_mb: 100,
    },
    routing: {
      auto_sync: true,
      auto_enable: true,
      tts_provider_id: "moss_tts",
      stt_provider_id: "moss_stt",
    },
  };

  let VOICES = [
    { id: "806c9695-6160-404e-8722-4f788d935af3", name: "轻快灵动女声", source: "api" },
    { id: "c6c0a40a-ea82-4468-9a21-333d3c4a76f6", name: "曼波有口音版", source: "api" },
    { id: "f80b6698-0066-430b-88a0-f0fb8796db34", name: "明太祖", source: "api" },
    { id: "ddc6e38b-6f55-4415-b21b-a88cad2cc1d9", name: "VOX AKUMA", source: "api" },
    { id: "f9a1416b-d006-4b77-9581-8f0e8ec1e401", name: "旁白 Jake", source: "api" },
    { id: "faf7f550-0627-4fc6-8db0-d3bfdad49358", name: "经验女教师", source: "api" },
  ];

  const context = {
    pluginName: "astrbot_plugin_moss_voice",
    displayName: "MOSS 设置",
    pageName: "settings",
    pageTitle: "MOSS 设置",
    locale: "zh-CN",
    i18n: { "zh-CN": { views: { settings: { title: "MOSS 设置" } } } },
    isDark: new URLSearchParams(location.search).get("theme") === "dark",
  };
  const listeners = new Set();
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function meta() {
    return {
      version: "3.0.0",
      api_key_configured: !NO_KEY,
      api_key_masked: NO_KEY ? "" : "moss****7890",
      api_key_source: NO_KEY ? "none" : "config",
    };
  }

  function publicConfig(includeKey) {
    const copy = JSON.parse(JSON.stringify(CONFIG));
    copy._meta = meta();
    if (!includeKey) copy.connection.api_key = "";
    return copy;
  }

  function providers() {
    return {
      available: true,
      api_key_configured: !NO_KEY,
      api_key_source: NO_KEY ? "none" : "config",
      tts: {
        id: CONFIG.routing.tts_provider_id,
        exists: true,
        enabled: true,
        loaded: true,
        selected: CONFIG.routing.auto_enable,
        routing_enabled: CONFIG.routing.auto_enable,
        model: CONFIG.tts.model,
      },
      stt: {
        id: CONFIG.routing.stt_provider_id,
        exists: true,
        enabled: true,
        loaded: true,
        selected: CONFIG.routing.auto_enable,
        routing_enabled: CONFIG.routing.auto_enable,
        model: CONFIG.stt.model,
      },
      current_tts: CONFIG.routing.auto_enable ? CONFIG.routing.tts_provider_id : "",
      current_stt: CONFIG.routing.auto_enable ? CONFIG.routing.stt_provider_id : "",
    };
  }

  function mergeConfig(incoming) {
    const merge = (target, source) => {
      Object.keys(source || {}).forEach((key) => {
        if (
          source[key] &&
          typeof source[key] === "object" &&
          !Array.isArray(source[key]) &&
          target[key] &&
          typeof target[key] === "object"
        ) {
          merge(target[key], source[key]);
        } else {
          target[key] = source[key];
        }
      });
    };
    merge(CONFIG, incoming);
  }

  function writeString(view, offset, value) {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  }

  function wavBase64() {
    const sampleRate = 22050;
    const seconds = 1.8;
    const samples = Math.floor(sampleRate * seconds);
    const buffer = new ArrayBuffer(44 + samples * 2);
    const view = new DataView(buffer);
    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + samples * 2, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, samples * 2, true);
    for (let index = 0; index < samples; index += 1) {
      const t = index / sampleRate;
      const envelope = Math.min(1, t * 12) * Math.min(1, (seconds - t) * 12);
      const sample =
        Math.sin(2 * Math.PI * 196 * t) * 0.22 +
        Math.sin(2 * Math.PI * 293.7 * t) * 0.12 +
        Math.sin(2 * Math.PI * 392 * t) * 0.06;
      view.setInt16(44 + index * 2, sample * envelope * 32767, true);
    }
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  function ttsResponse(body) {
    const audio = wavBase64();
    return {
      audio_base64: audio,
      mime: "audio/wav",
      format: "wav",
      bytes: Math.floor((audio.length * 3) / 4),
      elapsed_ms: 842,
      model: body.model,
      voice_id: body.voice_id,
      request_id: "req_demo_8f31",
    };
  }

  function transcriptResponse(body) {
    return {
      text: "S01: 欢迎使用 MOSS 语音测试。\nS02: 这段转写带说话人和时间码。",
      raw_text: "欢迎使用 MOSS 语音测试。这段转写带说话人和时间码。",
      segments: [
        { speaker: "S01", start: 0.16, end: 2.8, text: "欢迎使用 MOSS 语音测试。" },
        { speaker: "S02", start: 3.05, end: 5.62, text: "这段转写带说话人和时间码。" },
      ],
      model: body.model || CONFIG.stt.model,
      diarized: true,
      elapsed_ms: 1320,
      bytes: 84512,
      format: "wav",
      converted: false,
    };
  }

  window.AstrBotPluginView = {
    ready() {
      return Promise.resolve(context);
    },
    getContext() {
      return context;
    },
    getLocale() {
      return context.locale;
    },
    getI18n() {
      return context.i18n;
    },
    t(key, fallback) {
      const parts = String(key).split(".");
      let value = context.i18n["zh-CN"];
      for (const part of parts) value = value?.[part];
      return typeof value === "string" ? value : fallback || "";
    },
    onContext(handler) {
      if (typeof handler === "function") {
        listeners.add(handler);
        handler(context);
      }
      return () => listeners.delete(handler);
    },
    async apiGet(endpoint) {
      await delay(180);
      if (endpoint === "page/config") {
        return { config: publicConfig(true) };
      }
      if (endpoint === "page/status") {
        return { version: "3.0.0", config: publicConfig(false), providers: providers() };
      }
      if (endpoint === "page/voices") {
        if (NO_KEY) {
          return { voices: [], source: "none", notice: "先保存 API Key，才能读取账号音色。" };
        }
        return { voices: VOICES, source: "api", count: VOICES.length };
      }
      throw new Error(`mock: unknown GET ${endpoint}`);
    },
    async apiPost(endpoint, body) {
      await delay(420);
      if (endpoint === "page/config") {
        mergeConfig(body?.config || {});
        return {
          config: publicConfig(true),
          providers: providers(),
          synced: { ok: true, results: [], routing: { switched: ["moss_tts", "moss_stt"] } },
        };
      }
      if (endpoint === "page/test") {
        return {
          latency_ms: 73,
          api_key_masked: "moss****7890",
          sample_voice: { id: VOICES[0].id, name: VOICES[0].name },
        };
      }
      if (endpoint === "page/tts") {
        await delay(900);
        return ttsResponse(body || {});
      }
      if (endpoint === "page/stt") {
        await delay(1100);
        return transcriptResponse(body || {});
      }
      if (endpoint === "page/sync") {
        return {
          ok: true,
          boot: false,
          results: [
            { provider_id: "moss_tts", action: "updated" },
            { provider_id: "moss_stt", action: "updated" },
          ],
          routing: { switched: ["moss_tts", "moss_stt"] },
          providers: providers(),
        };
      }
      throw new Error(`mock: unknown POST ${endpoint}`);
    },
    async upload(endpoint, file) {
      await delay(1000);
      if (endpoint === "page/stt") {
        return transcriptResponse({ model: CONFIG.stt.model });
      }
      throw new Error(`mock: unknown upload ${endpoint}`);
    },
  };
  window.AstrBotPluginPage = window.AstrBotPluginView;
})();
