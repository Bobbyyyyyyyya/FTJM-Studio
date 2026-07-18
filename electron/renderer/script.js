const MAX_CHAT_HISTORY = 100;
let currentPhotoJobId = null;
let currentVideoJobId = null;
let currentAudioJobId = null;
let currentChatJobId = null;
let currentPhotoFilePath = null;
let currentVideoFilePath = null;
let currentAudioFilePath = null;
let currentTab = "photo";
let removeProgress = null;
let removeDone = null;
let removeError = null;
let removePreview = null;
let removeThinkingToken = null;
let chatHistory = [];
let chatThinkingBuffer = "";
const domCache = {};

const SVG = {
  play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m22 2-7 20-4-9-9-4Z"/><path d="m22 2-11 11"/></svg>',
  spinner: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>',
  welcome: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>',
};

function $(id) {
  if (!domCache[id]) domCache[id] = document.getElementById(id);
  return domCache[id];
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function init() {
  removeProgress = window.electronAPI.onProgress((msg) => {
    if (msg.job_id === currentPhotoJobId) {
      showPhotoStatus(msg.message);
      if (msg.progress != null) $("photoProgressFill").style.width = msg.progress + "%";
    }
    if (msg.job_id === currentVideoJobId) {
      showVideoStatus(msg.message);
      if (msg.progress != null) $("videoProgressFill").style.width = msg.progress + "%";
    }
    if (msg.job_id === currentAudioJobId) {
      showAudioStatus(msg.message);
      if (msg.progress != null) $("audioProgressFill").style.width = msg.progress + "%";
    }
    if (msg.job_id === currentChatJobId) {
      if (msg.progress != null) $("chatProgressFill").style.width = msg.progress + "%";
      if (msg.message) {
        showChatStatus(msg.message);
        updateThinkingMessage(msg.message);
      }
    }
  });

  removeDone = window.electronAPI.onDone((msg) => {
    if (msg.job_id === currentPhotoJobId) {
      $("photoProgressFill").style.width = "100%";
      setPhotoGenerating(false);
      currentPhotoFilePath = msg.file_path;
      showPhotoPreview(msg.file_path);
      $("btnSavePhoto").disabled = false;
      loadPhotoGallery();
    }
    if (msg.job_id === currentVideoJobId) {
      $("videoProgressFill").style.width = "100%";
      setVideoGenerating(false);
      currentVideoFilePath = msg.file_path;
      showVideoPreview(msg.file_path);
      $("btnSaveVideo").disabled = false;
      loadVideoGallery();
    }
    if (msg.job_id === currentAudioJobId) {
      $("audioProgressFill").style.width = "100%";
      setAudioGenerating(false);
      currentAudioFilePath = msg.file_path;
      showAudioPreview(msg.file_path);
      $("btnSaveAudio").disabled = false;
      loadAudioGallery();
    }
    if (msg.job_id === currentChatJobId) {
      $("chatProgressFill").style.width = "100%";
      removeThinkingMessage();
      chatThinkingBuffer = "";
      removeChatPreview();
      hideChatStatus();
      setChatSending(false);
      addChatMessage("assistant", msg.response, msg.prompt_tokens, msg.completion_tokens, msg.thinking);
      chatHistory.push({ role: "assistant", content: msg.response });
      while (chatHistory.length > MAX_CHAT_HISTORY) chatHistory.shift();
      if (msg.generated_files && msg.generated_files.length > 0) {
        for (const file of msg.generated_files) showChatGeneratedFile(file);
      }
    }
  });

  removeError = window.electronAPI.onError((msg) => {
    if (msg.job_id === currentPhotoJobId) { showPhotoError(msg.error); setPhotoGenerating(false); }
    if (msg.job_id === currentVideoJobId) { showVideoError(msg.error); setVideoGenerating(false); }
    if (msg.job_id === currentAudioJobId) { showAudioError(msg.error); setAudioGenerating(false); }
    if (msg.job_id === currentChatJobId) { removeThinkingMessage(); removeChatPreview(); showChatError(msg.error); setChatSending(false); chatThinkingBuffer = ""; }
  });

  removePreview = window.electronAPI.onPreview((msg) => {
    const imageData = msg.image_base64 || msg.image;
    if (!imageData) return;
    if (msg.job_id === currentPhotoJobId) {
      showLivePreview("photo", imageData);
    }
    if (msg.job_id === currentVideoJobId) {
      showLivePreview("video", imageData);
    }
    if (msg.job_id === currentChatJobId) {
      showChatPreview(imageData);
    }
  });

  removeThinkingToken = window.electronAPI.onThinkingToken((msg) => {
    if (msg.job_id === currentChatJobId) {
      chatThinkingBuffer += msg.token;
      updateThinkingMessage(chatThinkingBuffer);
    }
  });
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".nav-item").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.toggle("active", c.id === "tab-" + tab));
  if (tab === "models") loadModels();
}

function stopJob(type) {
  const jobIds = { photo: currentPhotoJobId, video: currentVideoJobId, audio: currentAudioJobId, chat: currentChatJobId };
  const jobId = jobIds[type];
  if (!jobId) return;
  window.electronAPI.sendCommand({ type: "cancel", job_id: jobId });
}

function showChatPreview(base64Data) {
  const messages = $("chatMessages");
  let existing = messages.querySelector(".chat-live-preview");
  const dataUrl = "data:image/jpeg;base64," + base64Data;

  if (existing) {
    existing.src = dataUrl;
  } else {
    const img = document.createElement("img");
    img.src = dataUrl;
    img.className = "chat-live-preview";
    img.alt = "Live preview";
    const thinkingEl = $("chatThinking");
    if (thinkingEl) {
      thinkingEl.parentNode.insertBefore(img, thinkingEl.nextSibling);
    } else {
      messages.appendChild(img);
    }
    messages.scrollTop = messages.scrollHeight;
  }
}

function removeChatPreview() {
  const el = document.querySelector(".chat-live-preview");
  if (el) el.remove();
}

function showLivePreview(type, base64Data) {
  const dataUrl = "data:image/jpeg;base64," + base64Data;

  if (type === "photo") {
    $("photoPreview").src = dataUrl;
    $("photoPreview").style.display = "block";
    $("photoPlaceholder").style.display = "none";
  } else if (type === "video") {
    const container = $("videoPlayer").parentElement;
    let existing = container.querySelector(".live-preview-img");
    if (!existing) {
      existing = document.createElement("img");
      existing.className = "live-preview-img";
      container.insertBefore(existing, $("videoPlayer"));
    }
    existing.src = dataUrl;
    $("videoPlaceholder").style.display = "none";
  }
}

// ── PHOTO ──

function setPhotoGenerating(generating) {
  $("btnGeneratePhoto").disabled = generating;
  $("btnStopPhoto").style.display = generating ? "inline-flex" : "none";
  $("btnSavePhoto").disabled = generating || !currentPhotoJobId;
  $("photoPrompt").disabled = generating;
  if (generating) {
    $("btnGeneratePhoto").innerHTML = SVG.spinner + ' Bezig...';
    $("photoStatusSection").style.display = "flex";
    $("photoStatusLabel").textContent = "Model laden...";
    $("photoProgressFill").className = "progress-fill";
    $("photoProgressFill").style.width = "0%";
  } else {
    $("btnGeneratePhoto").innerHTML = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Genereer Foto';
  }
}

function showPhotoStatus(message) {
  $("photoStatusSection").style.display = "flex";
  $("photoStatusLabel").textContent = message;
}

function showPhotoError(message) {
  $("photoStatusSection").style.display = "flex";
  $("photoStatusLabel").textContent = "Fout: " + message;
  $("photoProgressFill").className = "progress-fill";
  $("photoProgressFill").style.width = "0%";
}

async function showPhotoPreview(filePath) {
  const resolved = await window.electronAPI.getFilePath(filePath, "photo");
  if (!resolved) return;
  $("photoPreview").src = "file://" + resolved;
  $("photoPreview").style.display = "block";
  $("photoPlaceholder").style.display = "none";
}

function hidePhotoPreview() {
  $("photoPreview").style.display = "none";
  $("photoPreview").src = "";
  $("photoPlaceholder").style.display = "flex";
  currentPhotoJobId = null;
}

async function generatePhoto() {
  const prompt = $("photoPrompt").value.trim();
  if (!prompt) { showPhotoError("Voer een prompt in"); return; }
  hidePhotoPreview();
  setPhotoGenerating(true);
  currentPhotoJobId = "photo_" + Date.now();
  currentPhotoFilePath = null;
  try {
    await window.electronAPI.sendCommand({
      type: "generate_photo",
      job_id: currentPhotoJobId,
      prompt,
      model: $("photoModel").value,
      width: parseInt($("photoWidth").value),
      height: parseInt($("photoHeight").value),
      num_inference_steps: parseInt($("photoSteps").value),
      guidance_scale: parseFloat($("photoGuidance").value),
    });
  } catch (err) {
    showPhotoError("Fout: " + err.message);
    setPhotoGenerating(false);
  }
}

async function savePhoto() {
  if (!currentPhotoJobId || !currentPhotoFilePath) return;
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "save", gallery_type: "photos", job_id: currentPhotoJobId, file_path: currentPhotoFilePath });
    if (result.saved) { showPhotoStatus("Opgeslagen: " + result.saved); loadPhotoGallery(); }
  } catch (err) {}
}

// ── VIDEO ──

function setVideoGenerating(generating) {
  $("btnGenerateVideo").disabled = generating;
  $("btnStopVideo").style.display = generating ? "inline-flex" : "none";
  $("btnSaveVideo").disabled = generating || !currentVideoJobId;
  $("videoPrompt").disabled = generating;
  if (generating) {
    $("btnGenerateVideo").innerHTML = SVG.spinner + ' Bezig...';
    $("videoStatusSection").style.display = "flex";
    $("videoStatusLabel").textContent = "Model laden...";
    $("videoProgressFill").className = "progress-fill";
    $("videoProgressFill").style.width = "0%";
  } else {
    $("btnGenerateVideo").innerHTML = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Genereer Video';
  }
}

function showVideoStatus(message) {
  $("videoStatusSection").style.display = "flex";
  $("videoStatusLabel").textContent = message;
}

function showVideoError(message) {
  $("videoStatusSection").style.display = "flex";
  $("videoStatusLabel").textContent = "Fout: " + message;
  $("videoProgressFill").className = "progress-fill";
  $("videoProgressFill").style.width = "0%";
}

async function showVideoPreview(filePath) {
  const resolved = await window.electronAPI.getFilePath(filePath, "video");
  if (!resolved) return;
  $("videoPlayer").src = "file://" + resolved;
  $("videoPlayer").style.display = "block";
  $("videoPlaceholder").style.display = "none";
  $("videoPlayer").load();
}

function hideVideoPreview() {
  $("videoPlayer").style.display = "none";
  $("videoPlayer").src = "";
  $("videoPlaceholder").style.display = "flex";
  currentVideoJobId = null;
}

async function generateVideo() {
  const prompt = $("videoPrompt").value.trim();
  if (!prompt) { showVideoError("Voer een prompt in"); return; }
  hideVideoPreview();
  setVideoGenerating(true);
  currentVideoJobId = "video_" + Date.now();
  currentVideoFilePath = null;
  try {
    const resolution = parseInt($("videoResolution").value);
    await window.electronAPI.sendCommand({
      type: "generate_video",
      job_id: currentVideoJobId,
      prompt,
      num_frames: parseInt($("videoFrames").value),
      num_inference_steps: parseInt($("videoSteps").value),
      guidance_scale: parseFloat($("videoGuidance").value),
      adapter: $("videoAdapter").value,
      width: resolution,
      height: resolution,
    });
  } catch (err) {
    showVideoError("Fout: " + err.message);
    setVideoGenerating(false);
  }
}

async function saveVideo() {
  if (!currentVideoJobId || !currentVideoFilePath) return;
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "save", gallery_type: "video", job_id: currentVideoJobId, file_path: currentVideoFilePath });
    if (result.saved) { showVideoStatus("Opgeslagen: " + result.saved); loadVideoGallery(); }
  } catch (err) {}
}

// ── AUDIO ──

function setAudioGenerating(generating) {
  $("btnGenerateAudio").disabled = generating;
  $("btnStopAudio").style.display = generating ? "inline-flex" : "none";
  $("btnSaveAudio").disabled = generating || !currentAudioJobId;
  $("audioPrompt").disabled = generating;
  if (generating) {
    $("btnGenerateAudio").innerHTML = SVG.spinner + ' Bezig...';
    $("audioStatusSection").style.display = "flex";
    $("audioStatusLabel").textContent = "Model laden...";
    $("audioProgressFill").className = "progress-fill";
    $("audioProgressFill").style.width = "0%";
  } else {
    $("btnGenerateAudio").innerHTML = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg> Genereer Song';
  }
}

function showAudioStatus(message) {
  $("audioStatusSection").style.display = "flex";
  $("audioStatusLabel").textContent = message;
}

function showAudioError(message) {
  $("audioStatusSection").style.display = "flex";
  $("audioStatusLabel").textContent = "Fout: " + message;
  $("audioProgressFill").className = "progress-fill";
  $("audioProgressFill").style.width = "0%";
}

async function showAudioPreview(filePath) {
  const resolved = await window.electronAPI.getFilePath(filePath, "audio");
  if (!resolved) return;
  $("audioPlayer").src = "file://" + resolved;
  $("audioPlayer").style.display = "block";
  $("audioPlaceholder").style.display = "none";
  $("audioPlayer").load();
}

function hideAudioPreview() {
  $("audioPlayer").style.display = "none";
  $("audioPlayer").src = "";
  $("audioPlaceholder").style.display = "flex";
  currentAudioJobId = null;
}

async function generateAudio() {
  const prompt = $("audioPrompt").value.trim();
  if (!prompt) { showAudioError("Beschrijf je song concept"); return; }
  hideAudioPreview();
  setAudioGenerating(true);
  currentAudioJobId = "audio_" + Date.now();
  currentAudioFilePath = null;
  try {
    await window.electronAPI.sendCommand({
      type: "generate_audio",
      job_id: currentAudioJobId,
      prompt,
      duration_seconds: parseInt($("audioDuration").value),
      guidance_scale: parseFloat($("audioGuidance").value),
      model: $("audioModel").value,
    });
  } catch (err) {
    showAudioError("Fout: " + err.message);
    setAudioGenerating(false);
  }
}

async function saveAudio() {
  if (!currentAudioJobId || !currentAudioFilePath) return;
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "save", gallery_type: "audio", job_id: currentAudioJobId, file_path: currentAudioFilePath });
    if (result.saved) { showAudioStatus("Opgeslagen: " + result.saved); loadAudioGallery(); }
  } catch (err) {}
}

// ── GALLERY ──

function galleryItemHTML(v, type) {
  const previewFn = type === "photo" ? "previewGalleryPhoto" : type === "video" ? "previewGalleryVideo" : "previewGalleryAudio";
  const deleteFn = type === "photo" ? "deleteGalleryPhoto" : type === "video" ? "deleteGalleryVideo" : "deleteGalleryAudio";
  const safeName = escapeHtml(v.name);
  return `<div class="gallery-item">
    <span class="gallery-item-name" title="${safeName}">${safeName}</span>
    <span class="gallery-item-size">${v.size} ${v.size_unit}</span>
    <span class="gallery-item-actions">
      <button class="gallery-btn play" onclick="${previewFn}('${safeName}')" title="Bekijken">${type === "photo" ? SVG.eye : SVG.play}</button>
      <button class="gallery-btn delete" onclick="${deleteFn}('${safeName}')" title="Verwijderen">${SVG.trash}</button>
    </span>
  </div>`;
}

async function loadPhotoGallery() {
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "list", gallery_type: "photos" });
    const items = result.items || [];
    if (items.length === 0) { $("photoGallery").innerHTML = '<div class="gallery-empty">Nog geen opgeslagen foto\'s</div>'; return; }
    $("photoGallery").innerHTML = items.map((v) => galleryItemHTML(v, "photo")).join("");
  } catch (err) {}
}

async function loadVideoGallery() {
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "list", gallery_type: "video" });
    const items = result.items || [];
    if (items.length === 0) { $("videoGallery").innerHTML = '<div class="gallery-empty">Nog geen opgeslagen video\'s</div>'; return; }
    $("videoGallery").innerHTML = items.map((v) => galleryItemHTML(v, "video")).join("");
  } catch (err) {}
}

async function loadAudioGallery() {
  try {
    const result = await window.electronAPI.sendCommand({ type: "gallery", action: "list", gallery_type: "audio" });
    const items = result.items || [];
    if (items.length === 0) { $("audioGallery").innerHTML = '<div class="gallery-empty">Nog geen opgeslagen songs</div>'; return; }
    $("audioGallery").innerHTML = items.map((v) => galleryItemHTML(v, "audio")).join("");
  } catch (err) {}
}

async function previewGalleryPhoto(filename) {
  const resolved = await window.electronAPI.getFilePath(filename, "photo");
  if (!resolved) return;
  $("photoPreview").src = "file://" + resolved;
  $("photoPreview").style.display = "block";
  $("photoPlaceholder").style.display = "none";
  switchTab("photo");
}

async function previewGalleryVideo(filename) {
  const resolved = await window.electronAPI.getFilePath(filename, "video");
  if (!resolved) return;
  $("videoPlayer").src = "file://" + resolved;
  $("videoPlayer").style.display = "block";
  $("videoPlaceholder").style.display = "none";
  $("videoPlayer").load();
  switchTab("video");
}

async function previewGalleryAudio(filename) {
  const resolved = await window.electronAPI.getFilePath(filename, "audio");
  if (!resolved) return;
  $("audioPlayer").src = "file://" + resolved;
  $("audioPlayer").style.display = "block";
  $("audioPlaceholder").style.display = "none";
  $("audioPlayer").load();
  switchTab("audio");
}

async function deleteGalleryPhoto(filename) {
  try { await window.electronAPI.sendCommand({ type: "gallery", action: "delete", gallery_type: "photos", filename }); loadPhotoGallery(); } catch (err) {}
}
async function deleteGalleryVideo(filename) {
  try { await window.electronAPI.sendCommand({ type: "gallery", action: "delete", gallery_type: "video", filename }); loadVideoGallery(); } catch (err) {}
}
async function deleteGalleryAudio(filename) {
  try { await window.electronAPI.sendCommand({ type: "gallery", action: "delete", gallery_type: "audio", filename }); loadAudioGallery(); } catch (err) {}
}

// ── CHAT ──

function setChatSending(sending) {
  $("btnSendChat").disabled = sending;
  $("btnStopChat").style.display = sending ? "flex" : "none";
  $("chatInput").disabled = sending;
  if (sending) {
    $("btnSendChat").innerHTML = SVG.spinner;
  } else {
    $("btnSendChat").innerHTML = SVG.send;
  }
}

function showChatStatus(message) {
  $("chatStatusSection").style.display = "flex";
  $("chatStatusLabel").textContent = message;
}

function addThinkingMessage(text) {
  removeThinkingMessage();
  const messages = $("chatMessages");
  const welcome = messages.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  const details = document.createElement("details");
  details.className = "chat-msg assistant thinking-wrap";
  details.id = "chatThinking";

  const summary = document.createElement("summary");
  summary.className = "thinking-toggle";
  summary.innerHTML = '<span class="thinking-spinner"></span> Denkt...';

  const content = document.createElement("div");
  content.className = "thinking-stream-content";
  content.textContent = text || chatThinkingBuffer || "";

  details.appendChild(summary);
  details.appendChild(content);
  messages.appendChild(details);
  messages.scrollTop = messages.scrollHeight;
}

function updateThinkingMessage(text) {
  const el = $("chatThinking");
  if (el) {
    const content = el.querySelector(".thinking-stream-content");
    if (content) content.textContent = text;
    $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  }
}

function removeThinkingMessage() {
  const el = $("chatThinking");
  if (el) el.remove();
  delete domCache["chatThinking"];
}

function hideChatStatus() {
  $("chatStatusSection").style.display = "none";
}

function showChatError(message) {
  $("chatStatusSection").style.display = "flex";
  $("chatStatusLabel").textContent = "Fout: " + message;
  $("chatProgressFill").className = "progress-fill";
  $("chatProgressFill").style.width = "0%";
}

function addChatMessage(role, content, promptTokens, completionTokens, thinking) {
  const messages = $("chatMessages");
  const welcome = messages.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  const div = document.createElement("div");
  div.className = "chat-msg " + role;

  if (thinking && role === "assistant") {
    const thinkWrap = document.createElement("details");
    thinkWrap.className = "chat-thinking-wrap";
    const summary = document.createElement("summary");
    summary.className = "chat-thinking-toggle";
    summary.textContent = "Denkproces";
    const thinkContent = document.createElement("div");
    thinkContent.className = "chat-thinking-content";
    thinkContent.textContent = thinking;
    thinkWrap.appendChild(summary);
    thinkWrap.appendChild(thinkContent);
    div.appendChild(thinkWrap);
  }

  const textDiv = document.createElement("div");
  textDiv.className = "chat-msg-text";
  textDiv.textContent = content;
  div.appendChild(textDiv);

  if (promptTokens != null || completionTokens != null) {
    const meta = document.createElement("div");
    meta.className = "chat-msg-meta";
    meta.textContent = `${promptTokens || 0} in + ${completionTokens || 0} out`;
    div.appendChild(meta);
  }

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

async function showChatGeneratedFile(file) {
  const messages = $("chatMessages");
  const div = document.createElement("div");
  div.className = "chat-generated-file";

  if (file.type === "photo") {
    const resolved = await window.electronAPI.getFilePath(file.file_path, "photo");
    if (resolved) {
      const img = document.createElement("img");
      img.src = "file://" + resolved;
      img.className = "chat-preview-img";
      img.alt = "Genereerde foto";
      div.appendChild(img);
    }
  } else if (file.type === "video") {
    const resolved = await window.electronAPI.getFilePath(file.file_path, "video");
    if (resolved) {
      const vid = document.createElement("video");
      vid.src = "file://" + resolved;
      vid.controls = true;
      vid.className = "chat-preview-video";
      div.appendChild(vid);
    }
  } else if (file.type === "audio") {
    const resolved = await window.electronAPI.getFilePath(file.file_path, "audio");
    if (resolved) {
      const aud = document.createElement("audio");
      aud.src = "file://" + resolved;
      aud.controls = true;
      aud.className = "chat-preview-audio";
      div.appendChild(aud);
    }
  }

  const caption = document.createElement("div");
  caption.className = "chat-generated-caption";
  caption.textContent = `${file.type}: ${file.file_path}`;
  div.appendChild(caption);

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

async function sendChatMessage() {
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) return;

  addChatMessage("user", message);
  chatHistory.push({ role: "user", content: message });
  while (chatHistory.length > MAX_CHAT_HISTORY) chatHistory.shift();
  input.value = "";

  setChatSending(true);
  chatThinkingBuffer = "";
  addThinkingMessage("Aan het nadenken...");
  showChatStatus("Model laden (eerste keer downloadt het model)...");
  $("chatProgressFill").className = "progress-fill indeterminate";
  $("chatProgressFill").style.width = "0%";

  currentChatJobId = "chat_" + Date.now();

  try {
    await window.electronAPI.sendCommand({
      type: "chat",
      job_id: currentChatJobId,
      messages: chatHistory,
      model: $("chatModel").value,
      temperature: parseFloat($("chatTemperature").value),
      max_tokens: parseInt($("chatMaxTokens").value),
    });
  } catch (err) {
    removeThinkingMessage();
    showChatError("Fout: " + err.message);
    setChatSending(false);
  }
}

function handleChatKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChatMessage(); }
}

function clearChat() {
  chatHistory = [];
  removeThinkingMessage();
  hideChatStatus();
  $("chatMessages").innerHTML = `
    <div class="chat-welcome">
      <div class="chat-welcome-icon-wrap">${SVG.welcome}</div>
      <h3>AI Chat</h3>
      <p>Stel een vraag of begin een gesprek.</p>
      <p class="chat-welcome-sub">Het model draait lokaal op je Mac. Je kunt ook foto's, video's en audio laten genereren via het gesprek.</p>
    </div>
  `;
}

// ── INIT ──
init();
loadPhotoGallery();
loadVideoGallery();
loadAudioGallery();

// ── MODELS ──

const MODEL_CATEGORIES = {
  photo: { label: "Photo", icon: "camera" },
  video: { label: "Video", icon: "video" },
  audio: { label: "Audio", icon: "music" },
  chat: { label: "Chat", icon: "chat" },
};

const CATEGORY_ICONS = {
  photo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>',
  video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/></svg>',
  audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>',
};

async function loadModels() {
  $("modelsGrid").innerHTML = '<div class="models-loading">Modellen laden...</div>';

  try {
    const result = await window.electronAPI.sendCommand({ type: "model_management", action: "list" });
    const models = result.models || [];
    renderModels(models);
  } catch (err) {
    $("modelsGrid").innerHTML = '<div class="models-error">Fout bij laden: ' + escapeHtml(err.message) + '</div>';
  }
}

function renderModels(models) {
  const grid = $("modelsGrid");

  const installed = models.filter((m) => m.installed).length;
  const total = models.length;
  const totalSize = models.filter((m) => m.installed).reduce((sum, m) => sum + m.actual_size_gb, 0);
  $("modelsSummary").textContent = `${installed}/${total} geinstalleerd (${totalSize.toFixed(1)} GB)`;

  const categories = {};
  for (const m of models) {
    if (!categories[m.category]) categories[m.category] = [];
    categories[m.category].push(m);
  }

  let html = "";
  for (const [cat, catModels] of Object.entries(categories)) {
    const catInfo = MODEL_CATEGORIES[cat] || { label: cat };
    html += `<div class="model-category">`;
    html += `<div class="model-category-header">`;
    html += `<span class="model-category-icon">${CATEGORY_ICONS[cat] || ""}</span>`;
    html += `<h3>${escapeHtml(catInfo.label)}</h3>`;
    html += `</div>`;
    html += `<div class="model-category-list">`;

    for (const m of catModels) {
      const size = m.installed ? `${m.actual_size_gb} GB` : `~${m.estimated_size_gb} GB`;
      const statusClass = m.installed ? "installed" : "not-installed";
      const statusDot = m.installed
        ? '<span class="model-dot green" title="Geinstalleerd"></span>'
        : '<span class="model-dot red" title="Niet geinstalleerd"></span>';

      html += `<div class="model-card ${statusClass}">`;
      html += `<div class="model-card-info">`;
      html += `<div class="model-card-name">${statusDot} ${escapeHtml(m.name)}</div>`;
      html += `<div class="model-card-desc">${escapeHtml(m.description)}</div>`;
      html += `<div class="model-card-size">${size}</div>`;
      html += `</div>`;
      html += `<div class="model-card-actions">`;
      if (m.installed) {
        html += `<button class="btn btn-danger btn-sm" onclick="uninstallModel('${escapeHtml(m.id)}', '${escapeHtml(m.name)}')">Verwijder</button>`;
      } else {
        html += `<span class="model-status-badge not-installed">Niet geinstalleerd</span>`;
      }
      html += `</div>`;
      html += `</div>`;
    }

    html += `</div></div>`;
  }

  grid.innerHTML = html;
}

async function uninstallModel(modelId, modelName) {
  if (!confirm(`Weet je zeker dat je "${modelName}" wilt verwijderen?`)) return;

  const statusSection = $("modelsStatusSection");
  const statusLabel = $("modelsStatusLabel");
  statusSection.style.display = "flex";
  statusLabel.textContent = `${modelName} verwijderen...`;

  try {
    const result = await window.electronAPI.sendCommand({
      type: "model_management",
      action: "uninstall",
      model_id: modelId,
    });
    if (result.success) {
      statusLabel.textContent = result.message;
      loadModels();
    } else {
      statusLabel.textContent = "Fout: " + result.error;
    }
  } catch (err) {
    statusLabel.textContent = "Fout: " + err.message;
  }

  setTimeout(() => {
    statusSection.style.display = "none";
  }, 3000);
}

function checkUpdate() {
  window.electronAPI.sendCommand({ type: "check_update" });
}
