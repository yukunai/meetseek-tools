const $ = (selector) => document.querySelector(selector);
let authMode = "login";

async function postForm(url, form) {
  const response = await fetch(url, { method: "POST", body: form });
  const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.detail || data || "请求失败");
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

function setUser(user) {
  if (user) {
    $("#auth-open").textContent = user.name;
    $("#auth-logout").classList.remove("hidden");
    $("#member-badge").classList.remove("hidden");
    $("#member-badge").textContent = `${user.tier.toUpperCase()} 会员 · ${user.points || 0} 积分`;
  } else {
    $("#auth-open").textContent = "登录 / 注册";
    $("#auth-logout").classList.add("hidden");
    $("#member-badge").classList.add("hidden");
  }
}

async function loadMe() {
  const response = await fetch("/api/auth/me");
  const data = await response.json();
  setUser(data.user);
  return data.user;
}

$("#auth-open").addEventListener("click", () => { $("#auth-modal").hidden = false; });
$("#auth-close").addEventListener("click", () => { $("#auth-modal").hidden = true; });
document.querySelectorAll("[data-auth-mode]").forEach((button) => {
  button.addEventListener("click", () => { authMode = button.dataset.authMode; });
});

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData();
  form.append("email", $("#auth-email").value.trim());
  form.append("password", $("#auth-password").value);
  form.append("name", $("#auth-name").value.trim());
  try {
    const data = await postForm(`/api/auth/${authMode}`, form);
    setUser(data.user);
    $("#auth-message").textContent = "已登录";
    setTimeout(() => { $("#auth-modal").hidden = true; }, 500);
  } catch (error) {
    $("#auth-message").textContent = error.message;
  }
});

$("#auth-logout").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  setUser(null);
});

$("#forgot-open")?.addEventListener("click", () => {
  $("#forgot-email").value = $("#auth-email")?.value.trim() || "";
  $("#auth-modal").hidden = true;
  $("#forgot-modal").hidden = false;
});
$("#forgot-close")?.addEventListener("click", () => { $("#forgot-modal").hidden = true; });
$("#forgot-modal")?.addEventListener("click", (event) => {
  if (event.target === $("#forgot-modal")) $("#forgot-modal").hidden = true;
});
$("#forgot-form")?.addEventListener("submit", async (event) => {
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

$("#prompt-file").addEventListener("change", () => {
  const file = $("#prompt-file").files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  $("#prompt-preview").src = url;
  $("#prompt-preview-wrap").hidden = false;
  $("#prompt-preview-wrap").classList.remove("hidden");
});

$("#prompt-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const user = await loadMe();
  if (!user) {
    $("#auth-modal").hidden = false;
    $("#prompt-zh").innerHTML = '<span class="text-red-600">请先登录会员账号后再使用图片反推。</span>';
    return;
  }
  const file = $("#prompt-file").files[0];
  if (!file) {
    $("#prompt-zh").innerHTML = '<span class="text-red-600">请先上传图片。</span>';
    return;
  }
  $("#prompt-zh").textContent = "正在分析图片...";
  $("#prompt-en").textContent = "Generating prompt...";
  $("#prompt-provider").textContent = "";
  const form = new FormData();
  form.append("image", file);
  form.append("agree", $("#prompt-agree").checked ? "true" : "false");
  try {
    const data = await postForm("/api/prompt/image", form);
    await loadMe();
    $("#prompt-zh").textContent = data.zh;
    $("#prompt-en").textContent = data.en;
    $("#prompt-provider").textContent = data.provider === "local-fallback"
      ? `当前使用本地兜底提示；后台模型 ${data.model || ""} 没有成功完成图片分析。`
      : `已调用后台配置：${data.provider} / ${data.model}。`;
  } catch (error) {
    $("#prompt-zh").innerHTML = `<span class="text-red-600">${escapeHtml(error.message)}</span>`;
    $("#prompt-en").textContent = "";
  }
});

async function copyPrompt(selector, buttonSelector, label) {
  const text = $(selector).textContent.trim();
  if (!text || text.includes("会显示在这里") || text.includes("will be shown") || text.includes("结果会显示")) return;
  await navigator.clipboard.writeText(text);
  const button = $(buttonSelector);
  const old = button.textContent;
  button.textContent = label;
  setTimeout(() => { button.textContent = old; }, 1200);
}

$("#prompt-copy-zh").addEventListener("click", () => copyPrompt("#prompt-zh", "#prompt-copy-zh", "已复制"));
$("#prompt-copy-en").addEventListener("click", () => copyPrompt("#prompt-en", "#prompt-copy-en", "Copied"));
$("#translate-copy").addEventListener("click", () => copyPrompt("#translate-result", "#translate-copy", "已复制"));

async function translatePrompt(target) {
  const user = await loadMe();
  if (!user) {
    $("#auth-modal").hidden = false;
    $("#translate-result").innerHTML = '<span class="text-red-600">请先登录会员账号后再使用提示词翻译。</span>';
    return;
  }
  const form = new FormData();
  form.append("text", $("#translate-source").value.trim());
  form.append("target", target);
  $("#translate-result").textContent = "正在转换...";
  try {
    const data = await postForm("/api/prompt/translate", form);
    await loadMe();
    $("#translate-result").textContent = data.text;
  } catch (error) {
    $("#translate-result").innerHTML = `<span class="text-red-600">${escapeHtml(error.message)}</span>`;
  }
}

$("#translate-to-en").addEventListener("click", () => translatePrompt("en"));
$("#translate-to-zh").addEventListener("click", () => translatePrompt("zh"));

loadMe();
