const $ = (selector) => document.querySelector(selector);
window.meetseekAppLoaded = true;
let authMode = "login";
let currentToolUser = null;
let videoConfig = null;
let latestIpCheck = null;

document.querySelectorAll("[data-target]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById(button.dataset.target).scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

function showVideo(html) {
  const box = $("#video-result");
  box.hidden = false;
  box.classList.remove("hidden");
  box.innerHTML = html;
}

async function postForm(url, form) {
  const response = await fetch(url, { method: "POST", body: form });
  const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(data.detail || data || "请求失败");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function runAdScripts(container) {
  container.querySelectorAll("script").forEach((oldScript) => {
    const script = document.createElement("script");
    [...oldScript.attributes].forEach((attr) => script.setAttribute(attr.name, attr.value));
    script.text = oldScript.text;
    oldScript.replaceWith(script);
  });
}

function renderAdSlot(target, config) {
  const layout = config.layout || "banner";
  const items = (config.items || []).filter((item) => item.html);
  if (!items.length) return;
  target.classList.add("p-3");
  if (layout === "grid4") {
    target.innerHTML = `<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">${items.slice(0, 4).map((item) => `<div class="min-h-28 overflow-hidden rounded-lg bg-slate-50">${item.html}</div>`).join("")}</div>`;
  } else if (layout === "split") {
    target.innerHTML = `<div class="grid gap-3 md:grid-cols-2">${items.slice(0, 2).map((item) => `<div class="min-h-24 overflow-hidden rounded-lg bg-slate-50">${item.html}</div>`).join("")}</div>`;
  } else {
    target.innerHTML = `<div class="min-h-24 overflow-hidden rounded-lg bg-slate-50">${items[0].html}</div>`;
  }
  runAdScripts(target);
}

function setToolUser(user) {
  currentToolUser = user;
  const authOpen = $("#auth-open");
  const authLogout = $("#auth-logout");
  const badge = $("#tool-member-badge");
  if (!authOpen || !authLogout || !badge) return;
  if (user) {
    authOpen.textContent = user.name || user.email;
    authOpen.className = "rounded-full bg-white px-4 py-2 text-sm font-bold text-slate-900 ring-1 ring-slate-200";
    authLogout.classList.remove("hidden");
    badge.textContent = `${(user.tier || "free").toUpperCase()} 会员 · ${user.points || 0} 积分`;
    badge.classList.remove("hidden");
  } else {
    authOpen.textContent = "登录 / 注册";
    authOpen.className = "rounded-full bg-slate-950 px-4 py-2 text-sm font-bold text-white";
    authLogout.classList.add("hidden");
    badge.classList.add("hidden");
  }
}

async function loadToolUser() {
  try {
    const response = await fetch("/api/auth/me");
    const data = await response.json();
    setToolUser(data.user);
    return data.user;
  } catch {
    setToolUser(null);
    return null;
  }
}

function initToolAuth() {
  const authOpen = $("#auth-open");
  const authClose = $("#auth-close");
  const authModal = $("#auth-modal");
  const authForm = $("#auth-form");
  const authLogout = $("#auth-logout");
  const forgotOpen = $("#forgot-open");
  const forgotModal = $("#forgot-modal");
  const forgotClose = $("#forgot-close");
  const forgotForm = $("#forgot-form");
  if (!authOpen || !authClose || !authModal || !authForm || !authLogout) return;

  authOpen.addEventListener("click", () => { authModal.hidden = false; });
  authClose.addEventListener("click", () => { authModal.hidden = true; });
  authModal.addEventListener("click", (event) => {
    if (event.target === authModal) authModal.hidden = true;
  });

  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.addEventListener("click", () => { authMode = button.dataset.authMode; });
  });

  authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.submitter?.dataset.authMode) authMode = event.submitter.dataset.authMode;
    const form = new FormData();
    form.append("email", $("#auth-email").value.trim());
    form.append("password", $("#auth-password").value);
    form.append("name", $("#auth-name").value.trim());
    try {
      const data = await postForm(`/api/auth/${authMode}`, form);
      setToolUser(data.user);
      $("#auth-message").textContent = "已登录";
      setTimeout(() => { authModal.hidden = true; }, 500);
    } catch (error) {
      $("#auth-message").textContent = error.message;
    }
  });

  authLogout.addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setToolUser(null);
  });

  forgotOpen?.addEventListener("click", () => {
    $("#forgot-email").value = $("#auth-email")?.value.trim() || "";
    authModal.hidden = true;
    if (forgotModal) forgotModal.hidden = false;
  });
  forgotClose?.addEventListener("click", () => {
    if (forgotModal) forgotModal.hidden = true;
  });
  forgotModal?.addEventListener("click", (event) => {
    if (event.target === forgotModal) forgotModal.hidden = true;
  });
  forgotForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData();
    form.append("email", $("#forgot-email").value.trim());
    try {
      const data = await postForm("/api/auth/forgot-password", form);
      $("#forgot-message").textContent = data.message || "如果邮箱存在，重置链接会发送到邮箱。";
    } catch (error) {
      $("#forgot-message").textContent = error.message;
    }
  });
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function videoFormData() {
  const form = new FormData();
  form.append("url", $("#video-url").value.trim());
  form.append("quality", document.querySelector('input[name="video-quality"]:checked').value);
  form.append("agree", $("#video-agree").checked ? "true" : "false");
  return form;
}

document.querySelectorAll('input[name="video-quality"]').forEach((input) => {
  input.addEventListener("change", () => {
    syncQualityOptions();
  });
});

function syncQualityOptions() {
  document.querySelectorAll(".quality-option").forEach((label) => {
    const input = label.querySelector("input");
    const checked = input.checked;
    label.className = checked
      ? "quality-option flex cursor-pointer items-center gap-2 rounded-xl border border-orange-200 bg-orange-50 px-3 py-2 text-orange-700"
      : "quality-option flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-700";
  });
}

$("#video-info").addEventListener("click", async () => {
  try {
    showVideo("正在解析...");
    const data = await postForm("/api/video/info", videoFormData());
    showVideo(`
      <div class="flex gap-4">
        ${data.thumbnail ? `<img src="${data.thumbnail}" class="h-24 w-36 rounded-lg object-cover">` : ""}
        <div>
          <h3 class="font-black">${data.title}</h3>
          <p class="mt-1 text-sm text-slate-600">${data.uploader || ""}</p>
          <p class="mt-1 text-sm text-slate-500">时长：${data.duration ? Math.round(data.duration / 60) + " 分钟" : "未知"}</p>
          <div class="mt-3 flex flex-wrap gap-2 text-xs font-bold text-slate-600">
            <span class="rounded-full bg-white px-3 py-1">4K ${data.sizes?.["4k"] || "未知大小"}</span>
            <span class="rounded-full bg-white px-3 py-1">2K ${data.sizes?.["2k"] || "未知大小"}</span>
            <span class="rounded-full bg-white px-3 py-1">1080P ${data.sizes?.["1080p"] || "未知大小"}</span>
            <span class="rounded-full bg-white px-3 py-1">720P ${data.sizes?.["720p"] || "未知大小"}</span>
            <span class="rounded-full bg-white px-3 py-1">音频 ${data.sizes?.audio || "未知大小"}</span>
          </div>
        </div>
      </div>
    `);
  } catch (error) {
    showVideo(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#video-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    showVideo("任务已提交...");
    const task = await postForm("/api/video/download", videoFormData());
    await loadToolUser();
    pollTask(task.id);
  } catch (error) {
    showVideo(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#video-batch-submit").addEventListener("click", async () => {
  try {
    const form = new FormData();
    form.append("urls", $("#video-batch").value.trim());
    form.append("quality", document.querySelector('input[name="video-quality"]:checked').value);
    form.append("agree", $("#video-agree").checked ? "true" : "false");
    const data = await postForm("/api/video/batch", form);
    await loadToolUser();
    showVideo(`<div class="grid gap-3">${data.tasks.map((task) => `<div id="task-${task.id}" class="rounded-xl bg-white p-3">${task.id} 已排队</div>`).join("")}</div>`);
    data.tasks.forEach((task) => pollTask(task.id, `#task-${task.id}`));
  } catch (error) {
    showVideo(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

function coverFormData() {
  const form = new FormData();
  form.append("url", $("#cover-url").value.trim());
  form.append("agree", $("#cover-agree").checked ? "true" : "false");
  return form;
}

function showCover(html) {
  const box = $("#cover-result");
  box.hidden = false;
  box.classList.remove("hidden");
  box.innerHTML = html;
}

$("#cover-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    showCover("正在解析封面...");
    const data = await postForm("/api/video/cover-info", coverFormData());
    showCover(`
      <div class="grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
        ${data.thumbnail ? `<img src="${data.thumbnail}" class="w-full rounded-xl object-cover shadow-sm">` : `<div class="rounded-xl bg-white p-6 text-slate-500">没有解析到封面。</div>`}
        <div>
          <h3 class="text-lg font-black">${data.title}</h3>
          <p class="mt-1 text-sm text-slate-600">${data.uploader || ""}</p>
          <p class="mt-1 text-sm text-slate-500">时长：${data.duration ? Math.round(data.duration / 60) + " 分钟" : "未知"}</p>
          <div class="mt-4 flex flex-wrap gap-3">
            ${data.thumbnail ? `<button id="cover-download" type="button" class="rounded-xl bg-cyan-600 px-5 py-3 font-bold text-white">下载封面图</button>` : ""}
            <button id="cover-audio-inline" type="button" class="rounded-xl bg-slate-950 px-5 py-3 font-bold text-white">提取背景音乐</button>
          </div>
        </div>
      </div>
      <div id="cover-audio-task" class="mt-4"></div>
    `);
    if (data.thumbnail) {
      $("#cover-download").addEventListener("click", () => downloadCoverImage(data.thumbnail, data.title));
    }
    $("#cover-audio-inline").addEventListener("click", startCoverAudio);
  } catch (error) {
    showCover(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

async function downloadCoverImage(thumbnail, title) {
  const form = new FormData();
  form.append("thumbnail", thumbnail);
  form.append("title", title || "cover");
  const response = await fetch("/api/video/cover-download", { method: "POST", body: form });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    showCover(`<p class="text-red-600">${data.detail || "封面下载失败"}</p>`);
    return;
  }
  await loadToolUser();
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "meetseek-cover.jpg";
  link.click();
}

async function startCoverAudio() {
  try {
    const form = coverFormData();
    form.set("quality", "audio");
    const task = await postForm("/api/video/download", form);
    await loadToolUser();
    const target = document.querySelector("#cover-audio-task");
    if (target) {
      target.innerHTML = `<div id="cover-task-${task.id}" class="rounded-xl bg-white p-3">背景音乐任务已排队</div>`;
    } else {
      showCover(`<div id="cover-task-${task.id}" class="rounded-xl bg-white p-3">背景音乐任务已排队</div>`);
    }
    pollTask(task.id, `#cover-task-${task.id}`);
  } catch (error) {
    showCover(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
}

$("#cover-audio").addEventListener("click", startCoverAudio);

async function pollTask(id, target = null) {
  const response = await fetch(`/api/tasks/${id}`);
  const task = await response.json();
  const html = `
    <div class="grid gap-3">
      <div class="flex items-center justify-between">
        <b>${task.title || "下载任务"}</b>
        <span class="text-sm text-slate-500">${task.status} · ${task.quality || ""} · 第 ${task.attempt || 1} 次</span>
      </div>
      <div class="h-3 overflow-hidden rounded-full bg-slate-200">
        <div class="h-full bg-orange-600" style="width:${task.progress || 0}%"></div>
      </div>
      <p class="text-sm text-slate-600">${task.message || ""}${task.size ? ` · ${task.size}` : ""}${task.speed ? ` · ${task.speed}/s` : ""}${task.eta ? ` · 剩余 ${task.eta}s` : ""}</p>
      ${task.download_url ? `<a class="inline-flex w-fit rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" href="${task.download_url}">下载到本地</a><p class="text-xs text-slate-500">文件下载响应结束后，服务器会自动删除临时文件。</p>` : ""}
    </div>
  `;
  if (target) {
    document.querySelector(target).innerHTML = html;
  } else {
    showVideo(html);
  }
  if (task.status === "queued" || task.status === "running") {
    setTimeout(() => pollTask(id, target), 1600);
  }
}

let imageFile = null;
let imageBitmap = null;
let lastResultUrl = null;
const canvas = $("#paint");
const ctx = canvas.getContext("2d");
const mask = document.createElement("canvas");
const maskCtx = mask.getContext("2d");
const maskPreview = document.createElement("canvas");
const maskPreviewCtx = maskPreview.getContext("2d");
let painting = false;
let imageMode = "brush";
let lastPaintPoint = null;
const maskHistory = [];

$("#image-file").addEventListener("change", async (event) => {
  imageFile = event.target.files[0];
  if (!imageFile) return;
  imageBitmap = await createImageBitmap(imageFile);
  const scale = Math.min(1, 900 / imageBitmap.width);
  canvas.width = Math.round(imageBitmap.width * scale);
  canvas.height = Math.round(imageBitmap.height * scale);
  mask.width = canvas.width;
  mask.height = canvas.height;
  maskPreview.width = canvas.width;
  maskPreview.height = canvas.height;
  redrawImage();
  clearMask();
});

function redrawImage() {
  if (!imageBitmap) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(imageBitmap, 0, 0, canvas.width, canvas.height);
  drawMaskPreview();
}

function drawMaskPreview() {
  if (!mask.width || !mask.height) return;
  const maskData = maskCtx.getImageData(0, 0, mask.width, mask.height);
  const preview = maskPreviewCtx.createImageData(mask.width, mask.height);
  for (let index = 0; index < maskData.data.length; index += 4) {
    if (maskData.data[index] > 128) {
      preview.data[index] = 37;
      preview.data[index + 1] = 99;
      preview.data[index + 2] = 235;
      preview.data[index + 3] = 120;
    }
  }
  maskPreviewCtx.putImageData(preview, 0, 0);
  ctx.save();
  ctx.drawImage(maskPreview, 0, 0);
  ctx.restore();
}

function clearMask() {
  maskCtx.fillStyle = "black";
  maskCtx.fillRect(0, 0, mask.width, mask.height);
  redrawImage();
  maskHistory.length = 0;
}

$("#clear-mask").addEventListener("click", clearMask);
$("#brush").addEventListener("input", () => { $("#brush-size").textContent = $("#brush").value; });
$("#image-quality").addEventListener("input", () => { $("#quality-size").textContent = `${$("#image-quality").value}%`; });
$("#brush-mode").addEventListener("click", () => {
  imageMode = "brush";
  $("#brush-mode").className = "rounded-xl bg-blue-50 px-5 py-3 font-bold text-blue-700";
  $("#erase-mode").className = "rounded-xl bg-slate-100 px-5 py-3 font-bold text-slate-800";
});
$("#erase-mode").addEventListener("click", () => {
  imageMode = "erase";
  $("#erase-mode").className = "rounded-xl bg-blue-50 px-5 py-3 font-bold text-blue-700";
  $("#brush-mode").className = "rounded-xl bg-slate-100 px-5 py-3 font-bold text-slate-800";
});
$("#undo-mask").addEventListener("click", () => {
  const previous = maskHistory.pop();
  if (!previous) return;
  const img = new Image();
  img.onload = () => {
    maskCtx.clearRect(0, 0, mask.width, mask.height);
    maskCtx.drawImage(img, 0, 0);
    redrawImage();
  };
  img.src = previous;
});

function point(event) {
  const rect = canvas.getBoundingClientRect();
  const touch = event.touches?.[0];
  const x = (touch ? touch.clientX : event.clientX) - rect.left;
  const y = (touch ? touch.clientY : event.clientY) - rect.top;
  return { x: x * canvas.width / rect.width, y: y * canvas.height / rect.height };
}

function drawMaskStroke(from, to, brush) {
  maskCtx.save();
  maskCtx.lineCap = "round";
  maskCtx.lineJoin = "round";
  maskCtx.lineWidth = brush * 2;
  maskCtx.strokeStyle = imageMode === "erase" ? "black" : "white";
  maskCtx.fillStyle = maskCtx.strokeStyle;
  maskCtx.beginPath();
  if (from) {
    maskCtx.moveTo(from.x, from.y);
    maskCtx.lineTo(to.x, to.y);
    maskCtx.stroke();
  } else {
    maskCtx.arc(to.x, to.y, brush, 0, Math.PI * 2);
    maskCtx.fill();
  }
  maskCtx.restore();
}

function paint(event) {
  if (!painting) return;
  event.preventDefault();
  const currentPoint = point(event);
  const brush = Number($("#brush").value);
  drawMaskStroke(lastPaintPoint, currentPoint, brush);
  lastPaintPoint = currentPoint;
  redrawImage();
}

["mousedown", "touchstart"].forEach((name) => canvas.addEventListener(name, (event) => {
  if (mask.width) maskHistory.push(mask.toDataURL("image/png"));
  if (maskHistory.length > 12) maskHistory.shift();
  painting = true;
  lastPaintPoint = null;
  paint(event);
}));
["mousemove", "touchmove"].forEach((name) => canvas.addEventListener(name, paint));
["mouseup", "mouseleave", "touchend", "touchcancel"].forEach((name) => canvas.addEventListener(name, () => {
  painting = false;
  lastPaintPoint = null;
}));

function canvasBlob(target, type = "image/png", quality) {
  return new Promise((resolve) => target.toBlob(resolve, type, quality));
}

function cleanImageCanvas() {
  const output = document.createElement("canvas");
  output.width = canvas.width;
  output.height = canvas.height;
  output.getContext("2d").drawImage(imageBitmap, 0, 0, output.width, output.height);
  return output;
}

$("#image-submit").addEventListener("click", async () => {
  const result = $("#image-result");
  result.hidden = false;
  result.classList.remove("hidden");
  if (!imageFile) {
    result.innerHTML = '<p class="text-red-600">请先上传图片。</p>';
    return;
  }
  if (!$("#image-agree").checked) {
    result.innerHTML = '<p class="text-red-600">请先确认图片版权或授权。</p>';
    return;
  }
  result.innerHTML = "AI 正在修复...";
  const form = new FormData();
  form.append("image", await canvasBlob(cleanImageCanvas()), imageFile.name || "image.png");
  form.append("mask", await canvasBlob(mask), "mask.png");
  form.append("agree", "true");
  try {
    const response = await fetch("/api/image/cleanup", { method: "POST", body: form });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "处理失败");
    }
    await loadToolUser();
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    lastResultUrl = url;
    result.innerHTML = `<div class="grid gap-4 md:grid-cols-2"><div><p class="mb-2 text-sm font-bold text-slate-600">原图</p><img src="${URL.createObjectURL(imageFile)}" class="max-w-full rounded-xl"></div><div><p class="mb-2 text-sm font-bold text-slate-600">结果预览</p><img src="${url}" class="max-w-full rounded-xl"></div></div><a class="mt-3 inline-flex rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" download="meetseek-clean.png" href="${url}">下载结果</a>`;
  } catch (error) {
    result.innerHTML = `<p class="text-red-600">${escapeHtml(error.message)}</p>`;
  }
});

$("#convert-image").addEventListener("click", async () => {
  const result = $("#image-result");
  result.hidden = false;
  result.classList.remove("hidden");
  if (!imageBitmap) {
    result.innerHTML = '<p class="text-red-600">请先上传图片。</p>';
    return;
  }
  const output = document.createElement("canvas");
  output.width = imageBitmap.width;
  output.height = imageBitmap.height;
  output.getContext("2d").drawImage(imageBitmap, 0, 0);
  const type = $("#image-format").value;
  const quality = Number($("#image-quality").value) / 100;
  const blob = await canvasBlob(output, type, quality);
  const url = URL.createObjectURL(blob);
  const ext = type.includes("jpeg") ? "jpg" : type.split("/")[1];
  result.innerHTML = `<img src="${url}" class="max-w-full rounded-xl"><a class="mt-3 inline-flex rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" download="meetseek-converted.${ext}" href="${url}">下载转换后的图片</a><p class="mt-2 text-sm text-slate-500">大小约 ${(blob.size / 1024).toFixed(1)} KB</p>`;
});

function setupBananaWatermarkTool() {
  const fileInput = $("#banana-file");
  const canvas = $("#banana-paint");
  if (!fileInput || !canvas) return;
  const ctx = canvas.getContext("2d");
  const mask = document.createElement("canvas");
  const maskCtx = mask.getContext("2d");
  const preview = document.createElement("canvas");
  const previewCtx = preview.getContext("2d");
  const history = [];
  const state = {
    file: null,
    bitmap: null,
    painting: false,
    processing: false,
    mode: "brush",
    lastPoint: null,
  };

  function setMode(mode) {
    state.mode = mode;
    $("#banana-brush-mode").className = mode === "brush"
      ? "rounded-xl bg-yellow-50 px-5 py-3 font-bold text-yellow-800"
      : "rounded-xl bg-slate-100 px-5 py-3 font-bold text-slate-800";
    $("#banana-erase-mode").className = mode === "erase"
      ? "rounded-xl bg-yellow-50 px-5 py-3 font-bold text-yellow-800"
      : "rounded-xl bg-slate-100 px-5 py-3 font-bold text-slate-800";
  }

  function redraw() {
    if (!state.bitmap) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(state.bitmap, 0, 0, canvas.width, canvas.height);
    drawPreview();
  }

  function drawPreview() {
    if (!mask.width || !mask.height) return;
    const maskData = maskCtx.getImageData(0, 0, mask.width, mask.height);
    const imageData = previewCtx.createImageData(mask.width, mask.height);
    for (let index = 0; index < maskData.data.length; index += 4) {
      if (maskData.data[index] > 128) {
        imageData.data[index] = 249;
        imageData.data[index + 1] = 115;
        imageData.data[index + 2] = 22;
        imageData.data[index + 3] = 135;
      }
    }
    previewCtx.putImageData(imageData, 0, 0);
    ctx.drawImage(preview, 0, 0);
  }

  function clear() {
    if (!mask.width) return;
    maskCtx.fillStyle = "black";
    maskCtx.fillRect(0, 0, mask.width, mask.height);
    history.length = 0;
    redraw();
  }

  function pushHistory() {
    if (!mask.width) return;
    history.push(mask.toDataURL("image/png"));
    if (history.length > 12) history.shift();
  }

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    const touch = event.touches?.[0];
    const x = (touch ? touch.clientX : event.clientX) - rect.left;
    const y = (touch ? touch.clientY : event.clientY) - rect.top;
    return { x: x * canvas.width / rect.width, y: y * canvas.height / rect.height };
  }

  function drawStroke(from, to) {
    const brush = Number($("#banana-brush").value);
    maskCtx.save();
    maskCtx.lineCap = "round";
    maskCtx.lineJoin = "round";
    maskCtx.lineWidth = brush * 2;
    maskCtx.strokeStyle = state.mode === "erase" ? "black" : "white";
    maskCtx.fillStyle = maskCtx.strokeStyle;
    maskCtx.beginPath();
    if (from) {
      maskCtx.moveTo(from.x, from.y);
      maskCtx.lineTo(to.x, to.y);
      maskCtx.stroke();
    } else {
      maskCtx.arc(to.x, to.y, brush, 0, Math.PI * 2);
      maskCtx.fill();
    }
    maskCtx.restore();
  }

  function paint(event) {
    if (!state.painting) return;
    event.preventDefault();
    const currentPoint = point(event);
    drawStroke(state.lastPoint, currentPoint);
    state.lastPoint = currentPoint;
    redraw();
  }

  function cleanCanvas() {
    const output = document.createElement("canvas");
    output.width = canvas.width;
    output.height = canvas.height;
    output.getContext("2d").drawImage(state.bitmap, 0, 0, output.width, output.height);
    return output;
  }

  function setProcessing(processing) {
    state.processing = processing;
    ["#banana-submit", "#banana-opencv-submit"].forEach((selector) => {
      const button = $(selector);
      if (button) button.disabled = processing;
    });
  }

  function showImageResult(blob, filename) {
    const result = $("#banana-result");
    const url = URL.createObjectURL(blob);
    result.innerHTML = `<div class="grid gap-4 md:grid-cols-2"><div><p class="mb-2 text-sm font-bold text-slate-600">原图</p><img src="${URL.createObjectURL(state.file)}" class="max-w-full rounded-xl"></div><div><p class="mb-2 text-sm font-bold text-slate-600">结果预览</p><img src="${url}" class="max-w-full rounded-xl"></div></div><a class="mt-3 inline-flex rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" download="${filename}" href="${url}">下载清除后的图片</a>`;
  }

  function applyGrayscaleTest() {
    const result = $("#banana-result");
    result.hidden = false;
    result.classList.remove("hidden");
    if (!state.bitmap) {
      result.innerHTML = '<p class="text-red-600">请先上传 Banana 图片。</p>';
      return;
    }
    redraw();
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    for (let index = 0; index < data.length; index += 4) {
      const gray = 0.2126 * data[index] + 0.7152 * data[index + 1] + 0.0722 * data[index + 2];
      data[index] = gray;
      data[index + 1] = gray;
      data[index + 2] = gray;
    }
    ctx.putImageData(imageData, 0, 0);
    drawPreview();
    result.innerHTML = '<p class="text-slate-600">已在画布上应用灰度测试。这只是本地 Canvas 像素测试，不会上传，也不会扣积分。</p>';
  }

  async function submitCleanup(endpoint, busyText, filename) {
    const result = $("#banana-result");
    result.hidden = false;
    result.classList.remove("hidden");
    if (state.processing) return;
    if (!state.file || !state.bitmap) {
      result.innerHTML = '<p class="text-red-600">请先上传 Banana 生成的图片。</p>';
      return;
    }
    if (!$("#banana-agree").checked) {
      result.innerHTML = '<p class="text-red-600">请先确认图片版权或授权。</p>';
      return;
    }
    result.innerHTML = busyText;
    const form = new FormData();
    form.append("image", await canvasBlob(cleanCanvas()), state.file.name || "banana.png");
    form.append("mask", await canvasBlob(mask), "mask.png");
    form.append("agree", "true");
    form.append("radius", "3");
    form.append("algorithm", "telea");
    try {
      setProcessing(true);
      const response = await fetch(endpoint, { method: "POST", body: form });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "处理失败");
      }
      await loadToolUser();
      const blob = await response.blob();
      showImageResult(blob, filename);
    } catch (error) {
      result.innerHTML = `<p class="text-red-600">${escapeHtml(error.message)}</p>`;
    } finally {
      setProcessing(false);
    }
  }

  fileInput.addEventListener("change", async (event) => {
    state.file = event.target.files[0];
    if (!state.file) return;
    state.bitmap = await createImageBitmap(state.file);
    const scale = Math.min(1, 1000 / state.bitmap.width);
    canvas.width = Math.round(state.bitmap.width * scale);
    canvas.height = Math.round(state.bitmap.height * scale);
    mask.width = canvas.width;
    mask.height = canvas.height;
    preview.width = canvas.width;
    preview.height = canvas.height;
    clear();
  });

  $("#banana-brush").addEventListener("input", () => {
    $("#banana-brush-size").textContent = $("#banana-brush").value;
  });
  $("#banana-brush-mode").addEventListener("click", () => setMode("brush"));
  $("#banana-erase-mode").addEventListener("click", () => setMode("erase"));
  $("#banana-clear").addEventListener("click", clear);
  $("#banana-grayscale").addEventListener("click", applyGrayscaleTest);
  $("#banana-restore").addEventListener("click", redraw);
  $("#banana-undo").addEventListener("click", () => {
    const previous = history.pop();
    if (!previous) return;
    const img = new Image();
    img.onload = () => {
      maskCtx.clearRect(0, 0, mask.width, mask.height);
      maskCtx.drawImage(img, 0, 0);
      redraw();
    };
    img.src = previous;
  });
  $("#banana-auto-corner").addEventListener("click", () => {
    if (!mask.width) return;
    pushHistory();
    const width = Math.round(mask.width * 0.34);
    const height = Math.round(mask.height * 0.14);
    const x = Math.round(mask.width - width - mask.width * 0.035);
    const y = Math.round(mask.height - height - mask.height * 0.04);
    maskCtx.fillStyle = "white";
    maskCtx.fillRect(x, y, width, height);
    redraw();
  });

  ["mousedown", "touchstart"].forEach((name) => canvas.addEventListener(name, (event) => {
    pushHistory();
    state.painting = true;
    state.lastPoint = null;
    paint(event);
  }));
  ["mousemove", "touchmove"].forEach((name) => canvas.addEventListener(name, paint));
  ["mouseup", "mouseleave", "touchend", "touchcancel"].forEach((name) => canvas.addEventListener(name, () => {
    state.painting = false;
    state.lastPoint = null;
  }));

  $("#banana-opencv-submit").addEventListener("click", () => submitCleanup("/api/image/opencv-inpaint", "OpenCV 正在快速清除水印...", "banana-watermark-opencv.png"));
  $("#banana-submit").addEventListener("click", () => submitCleanup("/api/image/cleanup", "AI 正在清除水印...", "banana-watermark-ai.png"));
}

setupBananaWatermarkTool();

const metadataFile = $("#metadata-file");
const metadataCanvas = $("#metadata-canvas");
const metadataCtx = metadataCanvas.getContext("2d");
const metadataResult = $("#metadata-result");
const metadataPreview = $("#metadata-preview");
const metadataDownload = $("#metadata-download");
const metadataClear = $("#metadata-clear");

metadataFile.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("key", "metadata_strip");
  try {
    await postForm("/api/credits/charge", form);
    await loadToolUser();
  } catch (error) {
    alert(error.message);
    metadataFile.value = "";
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => {
      metadataCanvas.width = img.naturalWidth;
      metadataCanvas.height = img.naturalHeight;
      metadataCtx.clearRect(0, 0, metadataCanvas.width, metadataCanvas.height);
      metadataCtx.drawImage(img, 0, 0);

      const cleanDataUrl = metadataCanvas.toDataURL("image/png");
      metadataPreview.src = cleanDataUrl;
      metadataDownload.href = cleanDataUrl;
      metadataResult.hidden = false;
      metadataResult.classList.remove("hidden");
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
});

metadataClear.addEventListener("click", () => {
  metadataFile.value = "";
  metadataPreview.removeAttribute("src");
  metadataDownload.removeAttribute("href");
  metadataCanvas.width = 0;
  metadataCanvas.height = 0;
  metadataResult.hidden = true;
  metadataResult.classList.add("hidden");
});

document.querySelectorAll('input[name="compress-mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    document.querySelectorAll(".compress-option").forEach((label) => {
      const checked = label.querySelector("input").checked;
      label.className = checked
        ? "compress-option flex cursor-pointer items-start gap-3 rounded-xl border border-violet-200 bg-violet-50 p-4 text-violet-800"
        : "compress-option flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-slate-700";
    });
  });
});

$("#compress-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = $("#compress-result");
  result.hidden = false;
  result.classList.remove("hidden");
  const file = $("#compress-file").files[0];
  if (!file) {
    result.innerHTML = '<p class="text-red-600">请先选择要压缩的图片或视频。</p>';
    return;
  }
  if (!$("#compress-agree").checked) {
    result.innerHTML = '<p class="text-red-600">请先确认文件版权或授权。</p>';
    return;
  }
  result.innerHTML = "正在压缩，请保持页面打开...";
  const form = new FormData();
  form.append("file", file);
  form.append("mode", document.querySelector('input[name="compress-mode"]:checked').value);
  form.append("agree", "true");
  try {
    const response = await fetch("/api/media/compress", { method: "POST", body: form });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "压缩失败");
    }
    await loadToolUser();
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const outputName = response.headers.get("x-output-name") || "meetseek-compressed";
    const originalSize = Number(response.headers.get("x-original-size") || file.size);
    const compressedSize = Number(response.headers.get("x-compressed-size") || blob.size);
    const percent = originalSize ? Math.max(0, Math.round((1 - compressedSize / originalSize) * 100)) : 0;
    result.innerHTML = `
      <div class="grid gap-4 md:grid-cols-3">
        <div class="rounded-xl bg-white p-4"><b class="block text-sm text-slate-500">原始大小</b><span class="text-2xl font-black">${formatBytes(originalSize)}</span></div>
        <div class="rounded-xl bg-white p-4"><b class="block text-sm text-slate-500">压缩后</b><span class="text-2xl font-black">${formatBytes(compressedSize)}</span></div>
        <div class="rounded-xl bg-white p-4"><b class="block text-sm text-slate-500">体积变化</b><span class="text-2xl font-black">${percent > 0 ? `减少 ${percent}%` : "已优化"}</span></div>
      </div>
      <a class="mt-4 inline-flex rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" download="${outputName}" href="${url}">下载压缩后的文件</a>
      <p class="mt-2 text-xs text-slate-500">下载链接来自当前浏览器内存；服务器端临时文件已在响应结束后清理。</p>
    `;
  } catch (error) {
    result.innerHTML = `<p class="text-red-600">${escapeHtml(error.message)}</p>`;
  }
});

$("#compress-clear").addEventListener("click", () => {
  $("#compress-file").value = "";
  $("#compress-result").hidden = true;
  $("#compress-result").classList.add("hidden");
  $("#compress-result").innerHTML = "";
});

function selectedOfficeMode() {
  return document.querySelector('input[name="office-mode"]:checked').value;
}

function updateOfficeMode() {
  const mode = selectedOfficeMode();
  const fileInput = $("#office-files");
  if (mode === "images-to-pdf") {
    fileInput.accept = "image/jpeg,image/png,image/webp";
    fileInput.multiple = true;
    $("#office-help").textContent = "当前模式可上传 JPG、PNG、WebP 图片，最多 20 张，总大小限制 100MB。";
  } else {
    fileInput.accept = "application/pdf,.pdf";
    fileInput.multiple = false;
    $("#office-help").textContent = "当前模式需要上传一个 PDF 文件，单文件限制 100MB。";
  }
  fileInput.value = "";
  document.querySelectorAll(".office-option").forEach((label) => {
    const checked = label.querySelector("input").checked;
    label.className = checked
      ? "office-option flex cursor-pointer items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800"
      : "office-option flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-slate-700";
  });
}

document.querySelectorAll('input[name="office-mode"]').forEach((input) => {
  input.addEventListener("change", updateOfficeMode);
});

$("#office-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = $("#office-result");
  result.hidden = false;
  result.classList.remove("hidden");
  const files = [...$("#office-files").files];
  if (!files.length) {
    result.innerHTML = '<p class="text-red-600">请先上传要转换的文件。</p>';
    return;
  }
  if (!$("#office-agree").checked) {
    result.innerHTML = '<p class="text-red-600">请先确认文件版权或授权。</p>';
    return;
  }
  result.innerHTML = "正在转换，请保持页面打开...";
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("mode", selectedOfficeMode());
  form.append("agree", "true");
  try {
    const response = await fetch("/api/office/convert", { method: "POST", body: form });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "转换失败");
    }
    await loadToolUser();
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const outputName = response.headers.get("x-output-name") || "meetseek-converted";
    const originalSize = Number(response.headers.get("x-original-size") || files.reduce((sum, file) => sum + file.size, 0));
    const outputSize = Number(response.headers.get("x-output-size") || blob.size);
    result.innerHTML = `
      <div class="grid gap-4 md:grid-cols-2">
        <div class="rounded-xl bg-white p-4"><b class="block text-sm text-slate-500">上传大小</b><span class="text-2xl font-black">${formatBytes(originalSize)}</span></div>
        <div class="rounded-xl bg-white p-4"><b class="block text-sm text-slate-500">输出大小</b><span class="text-2xl font-black">${formatBytes(outputSize)}</span></div>
      </div>
      <a class="mt-4 inline-flex rounded-xl bg-slate-950 px-5 py-3 font-bold text-white" download="${outputName}" href="${url}">下载转换后的文件</a>
      <p class="mt-2 text-xs text-slate-500">PDF 转 Word 会优先提取可复制文本；扫描件 PDF 后续可以再接 OCR。</p>
    `;
  } catch (error) {
    result.innerHTML = `<p class="text-red-600">${escapeHtml(error.message)}</p>`;
  }
});

$("#office-clear").addEventListener("click", () => {
  $("#office-files").value = "";
  $("#office-result").hidden = true;
  $("#office-result").classList.add("hidden");
  $("#office-result").innerHTML = "";
});

const copyExample = "这是一款图片处理工具，可以上传图片，选择需要擦除的区域，然后自动修复画面。工具支持本地预览和下载结果，适合处理图片瑕疵。";

$("#copy-example").addEventListener("click", () => {
  $("#copy-source").value = copyExample;
});

$("#copy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = $("#copy-result");
  result.textContent = "正在转换...";
  const form = new FormData();
  form.append("text", $("#copy-source").value.trim());
  form.append("style", $("#copy-style").value);
  form.append("agree", $("#copy-agree").checked ? "true" : "false");
  try {
    const data = await postForm("/api/copy/rewrite", form);
    await loadToolUser();
    result.textContent = data.text;
    if (data.provider === "local-fallback") {
      result.textContent += "\n\n（当前使用本地兜底转换；配置 AI Key 后会自动走 AI 接口。）";
    }
  } catch (error) {
    result.innerHTML = `<span class="text-red-600">${escapeHtml(error.message)}</span>`;
  }
});

$("#copy-copy").addEventListener("click", async () => {
  const text = $("#copy-result").textContent.trim();
  if (!text || text === "转换后的内容会显示在这里。") return;
  await navigator.clipboard.writeText(text);
  $("#copy-copy").textContent = "已复制";
  setTimeout(() => { $("#copy-copy").textContent = "复制"; }, 1200);
});

const socialTemplates = {
  copy: "普通人做工具，最重要的不是堆功能，而是帮用户把一个小麻烦处理得足够顺手。\\n\\n从一个高频场景开始，把它做轻、做快、做漂亮。",
  code: "function shipTinyTool(idea) {\\n  const pain = findDailyPain(idea);\\n  const ui = makeItSimple(pain);\\n  return launch(ui);\\n}"
};

const socialRatios = {
  "16:9": { width: 1600, height: 900 },
  "1:1": { width: 1200, height: 1200 },
  "3:4": { width: 1200, height: 1600 },
  "4:3": { width: 1400, height: 1050 },
  "9:16": { width: 1080, height: 1920 }
};

const socialThemes = {
  glow: [["#111827", "#7c3aed", "#f97316"], "#ffffff", "rgba(255,255,255,0.16)", "rgba(255,255,255,0.26)"],
  sunset: [["#fb923c", "#ef4444", "#7c3aed"], "#ffffff", "rgba(255,255,255,0.18)", "rgba(255,255,255,0.28)"],
  ocean: [["#0f172a", "#0ea5e9", "#22c55e"], "#ffffff", "rgba(255,255,255,0.14)", "rgba(255,255,255,0.24)"],
  mono: [["#020617", "#111827", "#334155"], "#ffffff", "rgba(255,255,255,0.10)", "rgba(255,255,255,0.20)"],
  paper: [["#fff7ed", "#fef3c7", "#fde68a"], "#1f2937", "rgba(255,255,255,0.58)", "rgba(120,53,15,0.16)"],
  neon: [["#020617", "#111827", "#312e81"], "#ffffff", "rgba(15,23,42,0.46)", "rgba(34,211,238,0.34)"],
  forest: [["#052e16", "#15803d", "#bef264"], "#ffffff", "rgba(255,255,255,0.14)", "rgba(255,255,255,0.24)"],
  steel: [["#111827", "#64748b", "#e2e8f0"], "#ffffff", "rgba(255,255,255,0.15)", "rgba(255,255,255,0.28)"],
  candy: [["#fdf2f8", "#f9a8d4", "#a78bfa"], "#4c1d95", "rgba(255,255,255,0.62)", "rgba(76,29,149,0.12)"],
  aurora: [["#020617", "#164e63", "#581c87"], "#ffffff", "rgba(255,255,255,0.12)", "rgba(103,232,249,0.28)"],
  ink: [["#fafafa", "#e5e7eb", "#cbd5e1"], "#111827", "rgba(255,255,255,0.66)", "rgba(17,24,39,0.12)"],
  ember: [["#1c1917", "#7c2d12", "#ea580c"], "#ffffff", "rgba(255,255,255,0.13)", "rgba(254,215,170,0.26)"]
};

function socialText() {
  return ($("#social-input").value.trim() || "写点什么，让它变成一张可以分享的卡片。").slice(0, 900);
}

function updateSocialPreview() {
  const kind = $("#social-kind").value;
  const text = socialText();
  const preview = $("#social-preview");
  const ratio = $("#social-ratio").value;
  const [w, h] = ratio.split(":").map(Number);
  preview.dataset.theme = $("#social-theme").value;
  preview.style.aspectRatio = `${w} / ${h}`;
  $("#social-preview-text").textContent = text;
  $("#social-preview-text").className = kind === "code"
    ? "font-mono text-base font-bold leading-relaxed md:text-lg"
    : "font-sans text-xl font-black leading-snug md:text-2xl";
  $("#social-preview-author").textContent = `@${($("#social-author").value.trim() || "meetseek").replace(/^@/, "")}`;
}

function roundedRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function drawWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
  const lines = [];
  text.split("\n").forEach((paragraph) => {
    let line = "";
    for (const char of paragraph || " ") {
      const next = line + char;
      if (ctx.measureText(next).width > maxWidth && line) {
        lines.push(line);
        line = char;
      } else {
        line = next;
      }
    }
    lines.push(line);
  });
  lines.slice(0, maxLines).forEach((line, index) => {
    const suffix = index === maxLines - 1 && lines.length > maxLines ? "..." : "";
    ctx.fillText(line + suffix, x, y + index * lineHeight);
  });
}

function themeGradient(ctx, theme, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  const colors = (socialThemes[theme] || socialThemes.glow)[0];
  gradient.addColorStop(0, colors[0]);
  gradient.addColorStop(0.55, colors[1]);
  gradient.addColorStop(1, colors[2]);
  return gradient;
}

function drawSocialCard() {
  const canvas = $("#social-canvas");
  const ctx = canvas.getContext("2d");
  const theme = $("#social-theme").value;
  const kind = $("#social-kind").value;
  const size = socialRatios[$("#social-ratio").value] || socialRatios["16:9"];
  canvas.width = size.width;
  canvas.height = size.height;
  const width = canvas.width;
  const height = canvas.height;
  const minSide = Math.min(width, height);
  const scale = minSide / 900;
  const margin = Math.max(54 * scale, minSide * 0.075);
  const radius = Math.max(38 * scale, minSide * 0.045);
  const innerPad = Math.max(42 * scale, minSide * 0.06);
  const themeConfig = socialThemes[theme] || socialThemes.glow;
  const author = ($("#social-author").value.trim() || "meetseek").replace(/^@/, "");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = themeGradient(ctx, theme, width, height);
  ctx.fillRect(0, 0, width, height);

  ctx.globalAlpha = theme === "paper" ? 0.24 : 0.34;
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(width * 0.2, height * 0.18, minSide * 0.16, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 0.16;
  ctx.beginPath();
  ctx.arc(width * 0.82, height * 0.82, minSide * 0.24, 0, Math.PI * 2);
  ctx.fill();
  if (theme === "neon" || theme === "aurora" || theme === "ember") {
    ctx.globalAlpha = 0.46;
    ctx.fillStyle = theme === "ember" ? "#fed7aa" : "#22d3ee";
    ctx.beginPath();
    ctx.arc(width * 0.18, height * 0.28, minSide * 0.13, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = theme === "ember" ? "#fb923c" : "#f472b6";
    ctx.beginPath();
    ctx.arc(width * 0.82, height * 0.66, minSide * 0.18, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  ctx.shadowColor = "rgba(15, 23, 42, 0.35)";
  ctx.shadowBlur = 40 * scale;
  ctx.shadowOffsetY = 24 * scale;
  roundedRect(ctx, margin, margin, width - margin * 2, height - margin * 2, radius);
  ctx.fillStyle = themeConfig[2];
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = Math.max(2, 2 * scale);
  ctx.strokeStyle = themeConfig[3];
  ctx.stroke();

  const contentX = margin + innerPad;
  const contentY = margin + innerPad;
  const contentW = width - (margin + innerPad) * 2;
  const contentH = height - (margin + innerPad) * 2;
  const pillW = 190 * scale;
  const pillH = 48 * scale;
  roundedRect(ctx, contentX, contentY, pillW, pillH, pillH / 2);
  ctx.fillStyle = ["paper", "candy", "ink"].includes(theme) ? "rgba(17,24,39,0.08)" : "rgba(255,255,255,0.20)";
  ctx.fill();
  ctx.fillStyle = theme === "paper" ? "#92400e" : ["candy", "ink"].includes(theme) ? "#111827" : "rgba(255,255,255,0.92)";
  ctx.font = `700 ${Math.max(18, 24 * scale)}px Arial, sans-serif`;
  ctx.fillText("Social-Card", contentX + 28 * scale, contentY + 32 * scale);

  const textColor = themeConfig[1];
  const textY = contentY + pillH + 92 * scale;
  const authorY = contentY + contentH;
  const availableTextH = authorY - textY - 80 * scale;
  const fontSize = kind === "code" ? Math.max(24, 34 * scale) : Math.max(32, 52 * scale);
  const lineHeight = kind === "code" ? fontSize * 1.48 : fontSize * 1.34;
  const maxLines = Math.max(3, Math.floor(availableTextH / lineHeight));
  ctx.fillStyle = textColor;
  ctx.font = kind === "code" ? `700 ${fontSize}px Menlo, Consolas, monospace` : `900 ${fontSize}px Arial, sans-serif`;
  drawWrappedText(ctx, socialText(), contentX, textY, contentW, lineHeight, maxLines);

  ctx.fillStyle = theme === "paper" ? "#92400e" : ["candy", "ink"].includes(theme) ? "#374151" : "rgba(255,255,255,0.82)";
  ctx.font = `700 ${Math.max(20, 26 * scale)}px Arial, sans-serif`;
  ctx.fillText(`@${author}`, contentX, authorY);
}

["input", "change"].forEach((eventName) => {
  ["#social-input", "#social-theme", "#social-ratio", "#social-kind", "#social-author"].forEach((selector) => {
    $(selector).addEventListener(eventName, updateSocialPreview);
  });
});

$("#social-copy-template").addEventListener("click", () => {
  const kind = $("#social-kind").value;
  $("#social-input").value = socialTemplates[kind];
  updateSocialPreview();
});

$("#social-download").addEventListener("click", async () => {
  const form = new FormData();
  form.append("key", "social_card");
  try {
    await postForm("/api/credits/charge", form);
    await loadToolUser();
  } catch (error) {
    alert(error.message);
    return;
  }
  drawSocialCard();
  const link = document.createElement("a");
  link.download = "meetseek-social-card.png";
  link.href = $("#social-canvas").toDataURL("image/png");
  link.click();
});

updateSocialPreview();

function renderMemberSpace(data) {
  const user = data.user || {};
  const checkin = data.checkin || {};
  const config = data.checkin_config || {};
  const orders = data.payment_orders || [];
  const checked = Boolean(checkin.checked_today);
  const recent = checkin.recent || [];
  $("#member-content").innerHTML = `
    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-2xl bg-slate-950 p-5 text-white md:col-span-2">
        <p class="text-sm text-slate-300">当前会员</p>
        <h4 class="mt-2 text-2xl font-black">${escapeHtml(user.name || user.email || "会员")}</h4>
        <p class="mt-1 text-sm text-slate-300">${escapeHtml(user.email || "")}</p>
      </div>
      <div class="rounded-2xl bg-orange-50 p-5">
        <p class="text-sm font-bold text-orange-700">积分余额</p>
        <b class="mt-2 block text-3xl">${user.points || 0}</b>
      </div>
      <div class="rounded-2xl bg-blue-50 p-5">
        <p class="text-sm font-bold text-blue-700">会员等级</p>
        <b class="mt-2 block text-3xl">${String(user.tier || "free").toUpperCase()}</b>
      </div>
    </div>
    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section class="rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h4 class="text-xl font-black">${escapeHtml(config.title || "每日签到")}</h4>
            <p class="mt-1 text-sm leading-6 text-slate-600">${escapeHtml(config.description || "")}</p>
          </div>
          <span class="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-600">连续 ${checkin.current_streak || 0} 天</span>
        </div>
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-xl bg-white p-3"><b class="block text-2xl">${config.points || 0}</b><span class="text-xs text-slate-500">每日签到积分</span></div>
          <div class="rounded-xl bg-white p-3"><b class="block text-2xl">${config.streak_days || 7}</b><span class="text-xs text-slate-500">连续奖励周期</span></div>
          <div class="rounded-xl bg-white p-3"><b class="block text-2xl">+${config.streak_bonus || 0}</b><span class="text-xs text-slate-500">周期额外奖励</span></div>
        </div>
        <button id="member-checkin" class="mt-4 w-full rounded-xl ${checked ? "bg-slate-200 text-slate-500" : "bg-orange-600 text-white"} px-5 py-3 font-bold" type="button" ${checked ? "disabled" : ""}>
          ${checked ? "今天已签到" : "今日签到领积分"}
        </button>
        <p id="member-message" class="mt-3 min-h-5 text-sm text-slate-500"></p>
      </section>
      <section class="rounded-2xl border border-slate-200 bg-white p-5">
        <h4 class="font-black">会员资料</h4>
        <div class="mt-3 grid gap-2 text-sm text-slate-600">
          <p>加入时间：${user.created_at ? new Date(user.created_at * 1000).toLocaleDateString() : "--"}</p>
          <p>累计签到：${checkin.total_checkins || 0} 次</p>
          <p>今日状态：${checked ? "已签到" : "未签到"}</p>
        </div>
        <div class="mt-4 grid gap-2">
          <button id="member-pay" class="rounded-xl bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-700" type="button">充值积分</button>
          <button id="member-ad" class="rounded-xl bg-amber-50 px-4 py-3 text-sm font-bold text-amber-700" type="button">看广告赚积分</button>
        </div>
      </section>
    </div>
    <div class="grid gap-4 lg:grid-cols-2">
      <section class="rounded-2xl border border-slate-200 bg-white p-5">
        <h4 class="font-black">最近签到</h4>
        <div class="mt-3 grid gap-2 text-sm">
          ${recent.length ? recent.map((item) => `
            <div class="flex items-center justify-between rounded-xl bg-slate-50 p-3">
              <span>${item.day} · 连续 ${item.streak} 天</span>
              <b class="text-orange-600">+${item.points}</b>
            </div>
          `).join("") : "<p class=\"text-slate-500\">暂无签到记录。</p>"}
        </div>
      </section>
      <section class="rounded-2xl border border-slate-200 bg-white p-5">
        <h4 class="font-black">最近充值</h4>
        <div class="mt-3 grid gap-2 text-sm">
          ${orders.length ? orders.map((order) => `
            <div class="rounded-xl bg-slate-50 p-3">
              <b>${escapeHtml(order.package_name)}</b>
              <p class="text-slate-500">${order.amount} 元 · ${order.points} 积分 · ${order.status}</p>
            </div>
          `).join("") : "<p class=\"text-slate-500\">暂无充值订单。</p>"}
        </div>
      </section>
    </div>
  `;
}

async function loadMemberSpace() {
  const response = await fetch("/api/member/space");
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    $("#member-modal").hidden = true;
    $("#auth-modal").hidden = false;
    $("#auth-message").textContent = "请先登录后进入会员空间。";
    return;
  }
  if (!response.ok) throw new Error(data.detail || "会员空间读取失败");
  renderMemberSpace(data);
  setToolUser(data.user);
}

$("#member-open").addEventListener("click", async () => {
  $("#member-modal").hidden = false;
  $("#member-content").innerHTML = `<div class="rounded-2xl bg-slate-50 p-5 text-sm text-slate-500">正在读取会员信息...</div>`;
  try {
    await loadMemberSpace();
  } catch (error) {
    $("#member-content").innerHTML = `<div class="rounded-2xl bg-red-50 p-5 text-sm text-red-700">${escapeHtml(error.message)}</div>`;
  }
});

$("#member-close").addEventListener("click", () => { $("#member-modal").hidden = true; });
$("#member-modal").addEventListener("click", (event) => {
  if (event.target === $("#member-modal")) $("#member-modal").hidden = true;
});
$("#member-content").addEventListener("click", async (event) => {
  if (event.target.closest("#member-pay")) {
    $("#member-modal").hidden = true;
    $("#payment-open").click();
    return;
  }
  if (event.target.closest("#member-ad")) {
    $("#member-modal").hidden = true;
    $("#reward-open").click();
    return;
  }
  if (!event.target.closest("#member-checkin")) return;
  $("#member-message").textContent = "正在签到...";
  try {
    const data = await postForm("/api/member/checkin", new FormData());
    setToolUser(data.user);
    renderMemberSpace(data);
    $("#member-message").textContent = data.bonus
      ? `签到成功，获得 ${data.points} 积分，其中连续签到奖励 ${data.bonus} 分。`
      : `签到成功，获得 ${data.points} 积分。`;
  } catch (error) {
    $("#member-message").textContent = error.message;
  }
});

let paymentConfig = null;
let rewardConfig = null;
let rewardToken = "";
let rewardTimer = null;

async function loadPaymentConfig() {
  const data = await fetch("/api/payment/config").then((response) => response.json()).catch(() => null);
  if (!data) return;
  paymentConfig = data.payment || {};
  rewardConfig = data.reward || {};
  renderPaymentConfig();
  renderRewardConfig();
}

function renderPaymentConfig() {
  if (!paymentConfig) return;
  $("#payment-instruction-view").textContent = paymentConfig.instructions || "付款后提交凭证，管理员审核后加积分。";
  const packages = paymentConfig.packages || [];
  $("#payment-packages-view").innerHTML = packages.map((item, index) => `
    <button class="payment-package rounded-xl border ${index === 0 ? "border-orange-500 bg-orange-50" : "border-slate-200 bg-white"} p-4 text-left" data-package-id="${item.id}" type="button">
      <b>${item.name}</b>
      <p class="mt-1 text-sm text-slate-600">${item.points} 积分 · ${item.amount} 元</p>
    </button>
  `).join("");
  $("#payment-package-id").value = packages[0]?.id || "";
  const onlineActions = [];
  if (paymentConfig.stripe_enabled) {
    onlineActions.push(`<button class="payment-online rounded-xl bg-slate-950 px-5 py-3 font-black text-white" data-provider="stripe" type="button">Stripe 在线支付</button>`);
  }
  if (paymentConfig.xunhu_enabled) {
    onlineActions.push(`<button class="payment-online rounded-xl bg-orange-600 px-5 py-3 font-black text-white" data-provider="xunhu" type="button">虎皮椒/迅虎支付</button>`);
  }
  $("#payment-online-actions").innerHTML = onlineActions.join("");
  if (paymentConfig.wechat_qr) {
    $("#payment-wechat-view").src = paymentConfig.wechat_qr;
    $("#payment-wechat-view").classList.remove("hidden");
  }
  if (paymentConfig.alipay_qr) {
    $("#payment-alipay-view").src = paymentConfig.alipay_qr;
    $("#payment-alipay-view").classList.remove("hidden");
  }
}

function renderRewardConfig() {
  if (!rewardConfig) return;
  $("#reward-title-view").textContent = rewardConfig.title || "看广告赚积分";
  $("#reward-desc-view").textContent = `${rewardConfig.description || ""} 每次 ${rewardConfig.points || 0} 积分，每天最多 ${rewardConfig.daily_limit || 0} 次。`;
  $("#reward-countdown").textContent = `${rewardConfig.seconds || 30}s`;
}

async function loadMyPaymentOrders() {
  const box = $("#my-payment-orders");
  const data = await fetch("/api/payment/orders/mine").then(async (response) => {
    if (!response.ok) return null;
    return response.json();
  }).catch(() => null);
  if (!data) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = (data.orders || []).map((order) => `
    <div class="rounded-xl bg-slate-50 p-3">
      <b>${order.package_name}</b>
      <p class="text-slate-500">${order.amount} 元 · ${order.points} 积分 · ${order.method} · ${order.status}</p>
    </div>
  `).join("");
}

$("#payment-open").addEventListener("click", async () => {
  if (!paymentConfig) await loadPaymentConfig();
  $("#payment-modal").hidden = false;
  loadMyPaymentOrders();
});

$("#payment-close").addEventListener("click", () => { $("#payment-modal").hidden = true; });

$("#payment-packages-view").addEventListener("click", (event) => {
  const button = event.target.closest(".payment-package");
  if (!button) return;
  $("#payment-package-id").value = button.dataset.packageId;
  document.querySelectorAll(".payment-package").forEach((item) => {
    const active = item === button;
    item.classList.toggle("border-orange-500", active);
    item.classList.toggle("bg-orange-50", active);
    item.classList.toggle("border-slate-200", !active);
    item.classList.toggle("bg-white", !active);
  });
});

$("#payment-online-actions").addEventListener("click", async (event) => {
  const button = event.target.closest(".payment-online");
  if (!button) return;
  const form = new FormData();
  form.append("package_id", $("#payment-package-id").value);
  const provider = button.dataset.provider;
  const endpoint = provider === "stripe" ? "/api/payment/stripe/checkout" : "/api/payment/xunhu/checkout";
  $("#payment-message").textContent = "正在创建支付订单...";
  try {
    const data = await postForm(endpoint, form);
    if (!data.url) throw new Error("支付平台未返回跳转链接");
    window.location.href = data.url;
  } catch (error) {
    $("#payment-message").textContent = error.message;
  }
});

$("#payment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData();
  form.append("package_id", $("#payment-package-id").value);
  form.append("method", $("#payment-method").value);
  form.append("transaction_no", $("#payment-transaction").value.trim());
  if ($("#payment-proof").files[0]) form.append("screenshot", $("#payment-proof").files[0]);
  $("#payment-message").textContent = "正在提交...";
  try {
    const data = await postForm("/api/payment/orders", form);
    $("#payment-message").textContent = `已提交审核：${data.order.package_name}`;
    $("#payment-transaction").value = "";
    $("#payment-proof").value = "";
    await loadMyPaymentOrders();
  } catch (error) {
    $("#payment-message").textContent = error.message;
  }
});

$("#reward-open").addEventListener("click", async () => {
  if (!rewardConfig) await loadPaymentConfig();
  $("#reward-modal").hidden = false;
});

$("#reward-close").addEventListener("click", () => { $("#reward-modal").hidden = true; });

$("#reward-start").addEventListener("click", async () => {
  $("#reward-message").textContent = "正在开始广告计时...";
  try {
    const data = await postForm("/api/rewards/ad/start", new FormData());
    rewardToken = data.token;
    let left = data.seconds;
    $("#reward-claim").disabled = true;
    $("#reward-countdown").textContent = `${left}s`;
    clearInterval(rewardTimer);
    rewardTimer = setInterval(() => {
      left -= 1;
      $("#reward-countdown").textContent = `${Math.max(0, left)}s`;
      if (left <= 0) {
        clearInterval(rewardTimer);
        $("#reward-claim").disabled = false;
        $("#reward-message").textContent = `可以领取 ${data.points} 积分了。`;
      }
    }, 1000);
  } catch (error) {
    $("#reward-message").textContent = error.message;
  }
});

$("#reward-claim").addEventListener("click", async () => {
  const form = new FormData();
  form.append("token", rewardToken);
  try {
    const data = await postForm("/api/rewards/ad/claim", form);
    setToolUser(data.user);
    $("#reward-message").textContent = `已领取 ${data.points} 积分。`;
    $("#reward-claim").disabled = true;
  } catch (error) {
    $("#reward-message").textContent = error.message;
  }
});

async function loadPublicSettings() {
  const data = await fetch("/api/settings").then((response) => response.json()).catch(() => ({ ads: {} }));
  videoConfig = data.video || null;
  if (videoConfig) {
    const fileLimit = $("#video-file-limit");
    if (fileLimit) fileLimit.textContent = `${videoConfig.max_file_mb || 2048}MB`;
    syncQualityOptions();
  }
  Object.entries(data.ads || {}).forEach(([slot, config]) => {
    const target = document.querySelector(`[data-ad-slot="${slot}"]`);
    if (target && config.enabled) renderAdSlot(target, config);
  });
}

async function loadVisitorStats() {
  const box = $("#visitor-stats");
  if (!box) return;
  const data = await fetch("/api/visitor-stats").then((response) => response.json()).catch(() => null);
  if (!data) return;
  box.innerHTML = `
    <div class="rounded-xl bg-slate-50 p-3"><b class="block text-xl">${data.today.views}</b><span class="text-xs text-slate-500">今日访问</span></div>
    <div class="rounded-xl bg-slate-50 p-3"><b class="block text-xl">${data.month.views}</b><span class="text-xs text-slate-500">${data.month.key} 访问</span></div>
    <div class="rounded-xl bg-slate-50 p-3"><b class="block text-xl">${data.month.visitors}</b><span class="text-xs text-slate-500">本月访客</span></div>
    <div class="rounded-xl bg-slate-50 p-3"><b class="block text-xl">${data.total}</b><span class="text-xs text-slate-500">累计访问</span></div>
  `;
}

function renderIpHeaderInfo(headers = {}) {
  const box = $("#ip-header-info");
  if (!box) return;
  const userAgent = headers.user_agent || "未知浏览器";
  const shortUA = userAgent.length > 78 ? `${userAgent.slice(0, 78)}...` : userAgent;
  box.innerHTML = `
    <div class="flex items-center justify-between gap-3 rounded-2xl bg-white px-3 py-2">
      <span class="text-slate-400">协议</span><b class="text-slate-800">${escapeHtml((headers.protocol || "https").toUpperCase())}</b>
    </div>
    <div class="flex items-center justify-between gap-3 rounded-2xl bg-white px-3 py-2">
      <span class="text-slate-400">语言</span><b class="truncate text-slate-800">${escapeHtml(headers.accept_language || "未知")}</b>
    </div>
    <div class="rounded-2xl bg-white px-3 py-2">
      <span class="block text-slate-400">浏览器</span>
      <b class="mt-1 block break-all text-slate-800">${escapeHtml(shortUA)}</b>
    </div>
  `;
}

function renderIpBrowserInfo() {
  const box = $("#ip-browser-info");
  if (!box) return;
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "未知";
  const viewport = `${window.innerWidth} × ${window.innerHeight}`;
  const screenSize = `${window.screen?.width || "--"} × ${window.screen?.height || "--"}`;
  const language = navigator.language || "未知";
  box.innerHTML = [
    ["时区", timezone],
    ["窗口", viewport],
    ["屏幕", screenSize],
    ["语言", language],
    ["平台", navigator.platform || "未知"],
    ["在线状态", navigator.onLine ? "在线" : "离线"],
  ].map(([label, value]) => `
    <div class="rounded-2xl bg-white px-3 py-2">
      <span class="block text-xs font-bold text-slate-400">${escapeHtml(label)}</span>
      <b class="mt-1 block truncate text-slate-800">${escapeHtml(value)}</b>
    </div>
  `).join("");
}

function renderIpProbes(results = []) {
  const grid = $("#ip-probe-grid");
  if (!grid) return;
  if (!results.length) {
    grid.innerHTML = `<div class="rounded-2xl bg-slate-50 p-4 text-sm text-slate-400">暂无检测结果</div>`;
    return;
  }
  grid.innerHTML = results.map((item) => {
    const ok = item.status === "ok";
    const latency = item.latency_ms == null ? "--" : `${item.latency_ms}ms`;
    const color = ok ? "text-emerald-700 bg-emerald-50" : "text-rose-700 bg-rose-50";
    const dot = ok ? "bg-emerald-500" : "bg-rose-500";
    return `
      <div class="rounded-2xl border border-slate-100 bg-slate-50 p-4 transition hover:-translate-y-0.5 hover:bg-white hover:shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <div class="flex min-w-0 items-center gap-2">
            <span class="h-2.5 w-2.5 shrink-0 rounded-full ${dot}"></span>
            <b class="truncate text-slate-900">${escapeHtml(item.name)}</b>
          </div>
          <span class="rounded-full px-2 py-0.5 text-[11px] font-black ${color}">${ok ? "可达" : "异常"}</span>
        </div>
        <div class="mt-3 flex items-end justify-between">
          <span class="rounded-full bg-white px-2 py-1 text-xs font-bold text-slate-500">${escapeHtml(item.category || "网络")}</span>
          <span class="font-mono text-lg font-black text-slate-800">${escapeHtml(latency)}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderIpHealthSummary(me, probes) {
  const box = $("#ip-health-summary");
  if (!box) return;
  const results = probes?.results || [];
  const okCount = results.filter((item) => item.status === "ok").length;
  const latencies = results.map((item) => Number(item.latency_ms)).filter((value) => Number.isFinite(value));
  const average = latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : null;
  const statusTone = !results.length ? "text-slate-800" : okCount === results.length ? "text-emerald-700" : okCount ? "text-amber-700" : "text-rose-700";
  const statusText = !results.length ? "无结果" : okCount === results.length ? "全部可达" : `${okCount}/${results.length} 可达`;
  const checkedAt = me?.checked_at ? new Date(me.checked_at).toLocaleTimeString("zh-CN", { hour12: false }) : "--";
  box.innerHTML = `
    <div class="rounded-2xl border border-slate-100 bg-slate-50 p-4">
      <p class="text-xs font-black text-slate-400">连通状态</p>
      <p class="mt-1 text-lg font-black ${statusTone}">${escapeHtml(statusText)}</p>
    </div>
    <div class="rounded-2xl border border-slate-100 bg-slate-50 p-4">
      <p class="text-xs font-black text-slate-400">平均延迟</p>
      <p class="mt-1 font-mono text-lg font-black text-slate-800">${average == null ? "--" : `${average}ms`}</p>
    </div>
    <div class="rounded-2xl border border-slate-100 bg-slate-50 p-4">
      <p class="text-xs font-black text-slate-400">检测时间</p>
      <p class="mt-1 text-lg font-black text-slate-800">${escapeHtml(checkedAt)}</p>
    </div>
  `;
}

function buildIpReport() {
  if (!latestIpCheck?.me) return "MeetSeek IP 分流检测：暂无检测结果";
  const { me, probes } = latestIpCheck;
  const geo = me.geo || {};
  const location = [geo.country, geo.region, geo.city].filter(Boolean).join(" / ") || "未知";
  const org = [geo.asn, geo.org].filter(Boolean).join(" / ") || "未知";
  const probeLines = (probes?.results || []).map((item) => {
    const latency = item.latency_ms == null ? "--" : `${item.latency_ms}ms`;
    return `- ${item.name}: ${item.status === "ok" ? "可达" : "异常"} (${latency}, HTTP ${item.status_code || "--"})`;
  });
  return [
    "MeetSeek IP 分流检测报告",
    `公网 IP: ${me.ip || "未知"}`,
    `归属地: ${location}`,
    `ASN/运营商: ${org}`,
    `协议: ${(me.headers?.protocol || "").toUpperCase() || "未知"}`,
    `浏览器语言: ${me.headers?.accept_language || navigator.language || "未知"}`,
    `本机时区: ${Intl.DateTimeFormat().resolvedOptions().timeZone || "未知"}`,
    `检测时间: ${new Date(me.checked_at || Date.now()).toLocaleString("zh-CN", { hour12: false })}`,
    "",
    "站点连通性:",
    ...(probeLines.length ? probeLines : ["- 暂无结果"]),
  ].join("\n");
}

async function loadIpChecker() {
  if (!$("#ip-check")) return;
  const ipValue = $("#ip-current-value");
  const ipGeo = $("#ip-current-geo");
  const probeGrid = $("#ip-probe-grid");
  if (ipValue) ipValue.textContent = "检测中...";
  if (ipGeo) ipGeo.textContent = "正在读取归属地";
  if (probeGrid) probeGrid.innerHTML = `<div class="rounded-2xl bg-slate-50 p-4 text-sm text-slate-400">正在测试...</div>`;
  renderIpBrowserInfo();

  const [me, probes] = await Promise.all([
    fetch("/api/ip/me").then((response) => response.json()).catch(() => null),
    fetch("/api/ip/probes").then((response) => response.json()).catch(() => null),
  ]);

  if (me) {
    const geo = me.geo || {};
    const location = [geo.country, geo.region, geo.city].filter(Boolean).join(" · ");
    const org = [geo.asn, geo.org].filter(Boolean).join(" · ");
    if (ipValue) ipValue.textContent = me.ip || "未知";
    if (ipGeo) ipGeo.textContent = [location || "归属地未知", org].filter(Boolean).join(" ｜ ");
    renderIpHeaderInfo(me.headers || {});
  } else {
    if (ipValue) ipValue.textContent = "检测失败";
    if (ipGeo) ipGeo.textContent = "无法读取当前 IP 信息";
  }

  latestIpCheck = { me, probes };
  renderIpHealthSummary(me, probes);
  renderIpProbes(probes?.results || []);
}

$("#ip-refresh")?.addEventListener("click", loadIpChecker);
$("#ip-copy-report")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(buildIpReport());
    button.textContent = "已复制";
    button.classList.add("border-emerald-200", "bg-emerald-50", "text-emerald-700");
  } catch {
    button.textContent = "复制失败";
  }
  setTimeout(() => {
    button.textContent = original;
    button.classList.remove("border-emerald-200", "bg-emerald-50", "text-emerald-700");
  }, 1600);
});

loadPublicSettings();
loadPaymentConfig();
loadVisitorStats();
loadIpChecker();
initToolAuth();
loadToolUser();
