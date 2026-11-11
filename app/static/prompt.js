const $ = (selector) => document.querySelector(selector);

let imageModels = ["Nano banana", "gpt-image", "可灵", "即梦", "Flux", "Midjourney", "Stable Diffusion", "文心一言", "通义万相"];

const defaultPrompts = [
  {
    title: "未来城市雨夜",
    category: "赛博朋克",
    tags: ["城市", "夜景", "电影感"],
    models: [],
    gradient: "from-slate-950 via-violet-700 to-orange-500",
    zh: "未来城市雨夜，霓虹灯反射在湿润街道上，远处高楼与全息广告牌，孤独行人撑伞穿过街口，电影级构图，低角度镜头，强烈明暗对比，超高细节，真实质感，8K。",
    en: "futuristic rainy city night, neon reflections on wet streets, distant skyscrapers and holographic billboards, a lonely pedestrian crossing with an umbrella, cinematic composition, low angle shot, dramatic contrast, ultra detailed, realistic texture, 8k"
  },
  {
    title: "东方庭院茶室",
    category: "东方美学",
    tags: ["庭院", "静物", "自然光"],
    models: [],
    gradient: "from-emerald-900 via-lime-700 to-amber-300",
    zh: "安静的东方庭院茶室，木质窗棂，青苔石板，茶具置于低矮木桌上，晨光穿过竹影，空气中有细微尘埃，温润色调，极简构图，写实摄影，高级生活方式杂志风。",
    en: "quiet oriental courtyard tea room, wooden lattice windows, mossy stone floor, tea set on a low wooden table, morning light through bamboo shadows, subtle dust in the air, warm tones, minimal composition, realistic photography, premium lifestyle magazine style"
  },
  {
    title: "太空歌剧角色",
    category: "角色设计",
    tags: ["科幻", "人物", "盔甲"],
    models: [],
    gradient: "from-indigo-950 via-blue-700 to-cyan-400",
    zh: "太空歌剧女指挥官角色设定，银白色轻型装甲，肩部发光徽章，背后是巨型星舰舷窗和星云，坚定眼神，半身像，细腻皮肤纹理，概念艺术，电影海报级光影。",
    en: "space opera female commander character design, silver white lightweight armor, glowing shoulder emblem, giant starship window and nebula in the background, determined eyes, half body portrait, detailed skin texture, concept art, cinematic poster lighting"
  },
  {
    title: "极简产品海报",
    category: "商业视觉",
    tags: ["产品", "海报", "极简"],
    models: [],
    gradient: "from-zinc-900 via-zinc-600 to-zinc-200",
    zh: "极简高端产品海报，一只磨砂黑智能设备悬浮在柔和灰色背景中，边缘有精确高光，干净留白，工作室布光，商业广告摄影，奢侈科技品牌质感。",
    en: "minimal premium product poster, a matte black smart device floating on a soft gray background, precise rim highlights, clean negative space, studio lighting, commercial advertising photography, luxury tech brand texture"
  },
  {
    title: "童话森林小屋",
    category: "插画",
    tags: ["森林", "治愈", "童话"],
    models: [],
    gradient: "from-green-800 via-emerald-500 to-yellow-200",
    zh: "童话森林里的温暖小屋，蘑菇、萤火虫和蜿蜒小路，窗户透出暖黄色灯光，柔软圆润的造型，细腻手绘质感，治愈系儿童绘本插画，高饱和但舒适。",
    en: "warm cottage in a fairytale forest, mushrooms, fireflies and a winding path, warm yellow light from windows, soft rounded shapes, delicate hand drawn texture, healing children's picture book illustration, saturated yet comfortable colors"
  },
  {
    title: "复古胶片街拍",
    category: "摄影",
    tags: ["街拍", "胶片", "复古"],
    models: [],
    gradient: "from-stone-800 via-orange-700 to-amber-200",
    zh: "复古胶片街拍，一位穿风衣的人站在老街咖啡馆门口，午后阳光斜照，颗粒感胶片质感，浅景深，真实自然姿态，1970 年代杂志摄影风。",
    en: "vintage film street photography, a person in a trench coat standing outside an old street cafe, afternoon sunlight slanting in, grainy film texture, shallow depth of field, natural pose, 1970s magazine photography style"
  }
];
let prompts = defaultPrompts.map((item) => ({ ...item, tags: [...item.tags], models: [...(item.models || [])] }));
let promptDefaultCount = defaultPrompts.length;

let activeCategory = "全部";
let activeModel = "全部模型";
let currentSearch = "";
let searchTimer = null;
let currentPrompt = null;
let currentPromptIndex = -1;
let currentPromptId = "";
let authMode = "login";
let currentUser = null;
let pendingPromptImageFile = null;
let promptSaveInFlight = false;
let promptDraftNonce = "";
let activePromptLanguage = "zh";

function heartIcon(filled) {
  return filled
    ? `<svg class="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.08C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`
    : `<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z"/></svg>`;
}

function favoriteButtonHtml(item, promptId) {
  if (isAdItem(item) || !promptId) return "";
  const favorited = Boolean(item.favorited);
  return `
    <button class="favorite-prompt absolute right-3 top-3 grid h-10 w-10 place-items-center rounded-full bg-white/90 shadow-sm ring-1 ring-slate-200 backdrop-blur transition hover:scale-110 hover:bg-rose-50 ${favorited ? "text-red-500" : "text-slate-400 hover:text-red-500"}"
      type="button"
      aria-label="${favorited ? "取消收藏" : "收藏"}"
      title="${favorited ? "取消收藏" : "收藏"}"
      data-prompt-id="${promptId}"
      data-favorited="${favorited ? "true" : "false"}">
      ${heartIcon(favorited)}
    </button>
  `;
}

function setFavoriteButton(button, favorited) {
  if (!button) return;
  button.dataset.favorited = favorited ? "true" : "false";
  button.setAttribute("aria-label", favorited ? "取消收藏" : "收藏");
  button.title = favorited ? "取消收藏" : "收藏";
  button.innerHTML = heartIcon(favorited);
  button.classList.toggle("text-red-500", favorited);
  button.classList.toggle("text-slate-400", !favorited);
  button.classList.toggle("hover:text-red-500", !favorited);
}

function markPromptFavorite(promptId, favorited) {
  prompts = prompts.map((item) => Number(item.prompt_id || item._index || 0) === Number(promptId) ? { ...item, favorited } : item);
  if (currentPrompt && Number(currentPrompt.prompt_id || currentPrompt._index || 0) === Number(promptId)) {
    currentPrompt.favorited = favorited;
  }
}

async function togglePromptFavorite(promptId, button) {
  if (!promptId) return;
  const previous = button?.dataset.favorited === "true";
  setFavoriteButton(button, !previous);
  try {
    const response = await fetch(`/api/prompts/${encodeURIComponent(promptId)}/favorite`, { method: "POST" });
    const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text();
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) throw new Error(data.detail || data || "收藏失败");
    markPromptFavorite(promptId, Boolean(data.favorited));
    setFavoriteButton(button, Boolean(data.favorited));
    setFavoriteButton($("#modal-favorite"), Boolean(data.favorited));
  } catch (error) {
    setFavoriteButton(button, previous);
    $("#modal-translate-status").textContent = error.message || "收藏失败";
  }
}

function promptImageKey(index) {
  return `meetseek_prompt_image_${index}`;
}

function promptModelsKey(index) {
  return `meetseek_prompt_models_${index}`;
}

function promptDataKey(index) {
  return `meetseek_prompt_data_${index}`;
}

function createPromptNonce() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function setPromptBusy(isBusy) {
  promptSaveInFlight = isBusy;
  document.querySelectorAll("[data-prompt-save]").forEach((button) => {
    button.disabled = isBusy;
    button.classList.toggle("opacity-60", isBusy);
    button.classList.toggle("cursor-not-allowed", isBusy);
  });
  const deleteButton = $("#modal-delete");
  if (deleteButton) {
    deleteButton.disabled = isBusy;
    deleteButton.classList.toggle("opacity-60", isBusy);
    deleteButton.classList.toggle("cursor-not-allowed", isBusy);
  }
}

function setCopyButtonState(button, copied) {
  if (!button) return;
  const label = button.dataset.copyLabel || button.textContent || "复制";
  if (!button.dataset.copyLabel) button.dataset.copyLabel = label;
  button.textContent = copied ? "✅ 已复制" : label;
  button.classList.toggle("bg-emerald-700", copied);
  button.classList.toggle("bg-emerald-600", !copied);
}

function renderPromptLanguageTabs() {
  document.querySelectorAll("[data-prompt-tab]").forEach((button) => {
    const active = button.dataset.promptTab === activePromptLanguage;
    button.classList.toggle("bg-white", active);
    button.classList.toggle("text-slate-950", active);
    button.classList.toggle("shadow-sm", active);
    button.classList.toggle("text-slate-400", !active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-prompt-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.promptPanel !== activePromptLanguage);
  });
  document.querySelectorAll("[data-copy-modal]").forEach((button) => {
    button.classList.toggle("hidden", button.dataset.copyModal !== activePromptLanguage);
  });
}

function promptServerIndex(item, arrayIndex) {
  const parsed = Number(item?._index);
  return Number.isFinite(parsed) ? parsed : arrayIndex;
}

function promptArrayIndexFromServer(serverIndex) {
  return prompts.findIndex((item, arrayIndex) => promptServerIndex(item, arrayIndex) === serverIndex);
}

function promptItemId(item, arrayIndex) {
  return item?.id || String(promptServerIndex(item, arrayIndex));
}

function promptArrayIndexFromId(itemId) {
  return prompts.findIndex((item, arrayIndex) => promptItemId(item, arrayIndex) === itemId);
}

function promptMutationEndpoint() {
  return currentPromptId
    ? `/api/prompts/gallery/id/${encodeURIComponent(currentPromptId)}`
    : `/api/prompts/gallery/${currentPromptIndex}`;
}

function isDefaultPromptSelection() {
  return currentPromptId ? currentPromptId.startsWith("default-") : currentPromptIndex >= 0 && currentPromptIndex < promptDefaultCount;
}

function promptTaxonomyText(item) {
  return [item?.category, (item?.tags || []).join(" / ")].filter(Boolean).join(" · ");
}

function setPromptSaveText(text) {
  document.querySelectorAll("[data-prompt-save]").forEach((button) => {
    button.textContent = text;
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isAdItem(item) {
  return item?.kind === "ad";
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function parsePromptTags(value) {
  return value
    .split(/[,\uFF0C\u3001/]+/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 12);
}

function galleryQueryUrl() {
  const params = new URLSearchParams();
  if (currentSearch) params.set("search", currentSearch);
  if (activeCategory && activeCategory !== "全部") params.set("category", activeCategory);
  if (activeModel && activeModel !== "全部模型") params.set("model_engine", activeModel);
  const query = params.toString();
  return `/api/prompts/gallery${query ? `?${query}` : ""}`;
}

async function fetchPrompts() {
  try {
    const gallery = $("#prompt-gallery");
    if (gallery) {
      gallery.innerHTML = `
        <div class="break-inside-avoid rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="h-56 animate-pulse rounded-xl bg-slate-100"></div>
          <div class="mt-4 h-4 animate-pulse rounded bg-slate-100"></div>
          <div class="mt-2 h-4 w-2/3 animate-pulse rounded bg-slate-100"></div>
        </div>
      `;
    }
    const response = await fetch(galleryQueryUrl());
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "提示词图库读取失败");
    imageModels = data.models || imageModels;
    promptDefaultCount = Number(data.default_count || defaultPrompts.length);
    prompts = (data.prompts || []).map((item) => ({
      ...item,
      id: item.id ? String(item.id) : "",
      _index: Number.isFinite(Number(item._index)) ? Number(item._index) : undefined,
      prompt_id: Number.isFinite(Number(item.prompt_id)) ? Number(item.prompt_id) : Number(item._index || 0),
      favorited: Boolean(item.favorited),
      kind: item.kind || "prompt",
      tags: Array.isArray(item.tags) ? item.tags : [],
      models: Array.isArray(item.models) ? item.models : [],
    }));
  } catch {
    promptDefaultCount = defaultPrompts.length;
    prompts = defaultPrompts.map((item) => ({ ...item, tags: [...item.tags], models: [...(item.models || [])] }));
  }
  renderCategories();
  renderModelFilters();
  renderGallery();
}

const loadPromptGallery = fetchPrompts;

function renderCategories() {
  const baseCategories = ["全部", "历史", "漫画", "人物", "设计", "商品", "电商", "角色设计", "商业视觉", "插画", "摄影"];
  const categories = [...new Set([...baseCategories, activeCategory, ...prompts.map((item) => item.category)].filter(Boolean))];
  $("#prompt-categories").innerHTML = categories.map((category) => `
    <button class="category-btn rounded-full px-4 py-2 text-sm font-bold transition ${category === activeCategory ? "bg-slate-900 text-white" : "bg-slate-50 text-slate-700 hover:bg-slate-100"}" data-category="${escapeHtml(category)}" type="button">${escapeHtml(category)}</button>
  `).join("");
}

function renderModelFilters() {
  const models = ["全部模型", ...imageModels];
  $("#prompt-model-filters").innerHTML = models.map((model) => `
    <button class="model-filter rounded-full px-4 py-2 text-sm font-bold ${model === activeModel ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-700"}" data-model="${escapeHtml(model)}" type="button">${escapeHtml(model)}</button>
  `).join("");
}

function renderGallery() {
  const keyword = $("#prompt-search").value.trim().toLowerCase();
  const filtered = prompts.map((item, arrayIndex) => ({
    item,
    arrayIndex,
    serverIndex: promptServerIndex(item, arrayIndex),
    itemId: promptItemId(item, arrayIndex)
  })).filter(({ item }) => {
    const matchCategory = activeCategory === "全部" || item.category === activeCategory;
    const matchModel = isAdItem(item) || activeModel === "全部模型" || (item.models || []).includes(activeModel);
    const haystack = `${item.title} ${item.category} ${item.tags.join(" ")} ${(item.models || []).join(" ")} ${item.zh} ${item.en} ${item.description || ""} ${item.url || ""}`.toLowerCase();
    return matchCategory && matchModel && (!keyword || haystack.includes(keyword));
  }).sort((left, right) => {
    const leftWeight = Number(left.item.sort_order || 0);
    const rightWeight = Number(right.item.sort_order || 0);
    if (leftWeight || rightWeight) {
      if (leftWeight !== rightWeight) return rightWeight - leftWeight;
    }
    const leftCustom = left.serverIndex >= promptDefaultCount;
    const rightCustom = right.serverIndex >= promptDefaultCount;
    if (leftCustom && rightCustom) return right.serverIndex - left.serverIndex;
    if (leftCustom !== rightCustom) return leftCustom ? -1 : 1;
    return left.serverIndex - right.serverIndex;
  });
  $("#prompt-gallery").innerHTML = filtered.map(({ item, serverIndex, itemId }) => isAdItem(item) ? renderAdCard(item, serverIndex, itemId) : `
    <article class="prompt-card masonry-item relative overflow-hidden border border-slate-200 bg-white text-left shadow-sm transition hover:-translate-y-0.5">
      <button class="prompt-open block w-full text-left" data-index="${serverIndex}" data-id="${escapeHtml(itemId)}" type="button">
        ${item.image
          ? `<div class="prompt-gallery-image-wrap"><img src="${escapeHtml(item.image)}" class="prompt-gallery-image" alt="${escapeHtml(item.title)}" loading="lazy"></div>`
          : `<div class="min-h-72 bg-gradient-to-br ${item.gradient} p-5 text-white">
              <div class="flex min-h-64 flex-col justify-between rounded-2xl border border-white/20 bg-white/10 p-4 backdrop-blur">
                <span class="w-fit rounded-full bg-white/20 px-3 py-1 text-xs font-bold">${escapeHtml(item.category)}</span>
                <h3 class="text-2xl font-black">${escapeHtml(item.title)}</h3>
                <span class="text-xs font-bold text-white/80">点开后可上传案例图</span>
              </div>
            </div>`}
        <div class="p-5">
          <p class="line-clamp-3 text-sm leading-6 text-slate-600">${escapeHtml(item.zh)}</p>
          <div class="mt-4 flex flex-wrap gap-2">${item.tags.map((tag) => `<span class="rounded-full bg-slate-100 px-2 py-1 text-xs font-bold text-slate-500">${escapeHtml(tag)}</span>`).join("")}</div>
          <div class="mt-3 flex flex-wrap gap-2">${(item.models || []).slice(0, 4).map((model) => `<span class="rounded-full bg-emerald-50 px-2 py-1 text-xs font-black text-emerald-700">${escapeHtml(model)}</span>`).join("")}${(item.models || []).length > 4 ? `<span class="rounded-full bg-slate-100 px-2 py-1 text-xs font-bold text-slate-500">+${item.models.length - 4}</span>` : ""}</div>
        </div>
      </button>
      ${favoriteButtonHtml(item, item.prompt_id || serverIndex)}
    </article>
  `).join("") || `<div class="rounded-xl bg-white p-6 text-slate-500">没有匹配的提示词。</div>`;
}

function renderAdCard(item, index, itemId) {
  const url = safeExternalUrl(item.url || "");
  const card = `
    <article class="prompt-card masonry-item overflow-hidden border border-orange-200 bg-white text-left shadow-sm">
      ${item.image
        ? `<div class="prompt-gallery-image-wrap"><img src="${escapeHtml(item.image)}" class="prompt-gallery-image" alt="${escapeHtml(item.title)}" loading="lazy"></div>`
        : `<div class="min-h-72 bg-gradient-to-br from-orange-600 via-amber-400 to-rose-500 p-5 text-white">
            <div class="flex min-h-64 flex-col justify-between rounded-2xl border border-white/25 bg-white/10 p-4 backdrop-blur">
              <span class="w-fit rounded-full bg-white/25 px-3 py-1 text-xs font-bold">广告</span>
              <h3 class="text-2xl font-black">${escapeHtml(item.title)}</h3>
            </div>
          </div>`}
      <div class="p-5">
        <div class="mb-3 flex flex-wrap gap-2">
          <span class="rounded-full bg-orange-100 px-2 py-1 text-xs font-black text-orange-700">广告</span>
          ${(item.tags || []).slice(0, 4).map((tag) => `<span class="rounded-full bg-slate-100 px-2 py-1 text-xs font-bold text-slate-500">${escapeHtml(tag)}</span>`).join("")}
        </div>
        <h3 class="text-xl font-black text-slate-950">${escapeHtml(item.title)}</h3>
        <p class="mt-3 line-clamp-4 text-sm leading-6 text-slate-600">${escapeHtml(item.description || item.zh || "")}</p>
        <div class="mt-4 flex flex-wrap gap-2">
          ${url ? `<a class="rounded-xl bg-slate-950 px-4 py-2 text-sm font-black text-white" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.cta || "查看详情")}</a>` : ""}
          ${currentUser?.is_prompt_admin ? `<button class="prompt-open rounded-xl bg-orange-50 px-4 py-2 text-sm font-black text-orange-700" data-index="${index}" data-id="${escapeHtml(itemId || String(index))}" type="button">编辑广告</button>` : ""}
        </div>
      </div>
    </article>
  `;
  return card;
}

function setUser(user) {
  currentUser = user;
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
  updatePromptAdminControls();
}

function updatePromptAdminControls() {
  const isAdmin = Boolean(currentUser?.is_prompt_admin);
  const adMode = isAdItem(currentPrompt);
  document.body.classList.toggle("prompt-admin", isAdmin);
  document.querySelectorAll("[data-prompt-admin-only]").forEach((item) => {
    item.classList.toggle("hidden", !isAdmin);
  });
  $("#modal-api-toggle")?.classList.toggle("hidden", !isAdmin || adMode);
  $("#modal-model-settings")?.classList.toggle("hidden", !isAdmin || adMode);
  $("#modal-ad-editor")?.classList.toggle("hidden", !isAdmin || !adMode);
  $("#modal-prompt-editor")?.classList.toggle("hidden", adMode);
  const deleteButton = $("#modal-delete");
  if (deleteButton) {
    const canDelete = isAdmin && currentPromptIndex >= 0;
    deleteButton.classList.toggle("hidden", !canDelete);
    deleteButton.textContent = isDefaultPromptSelection() ? "下架此卡片" : "删除此卡片";
  }
  const apiToggle = $("#modal-use-api");
  if (apiToggle) {
    apiToggle.disabled = !isAdmin;
    if (!isAdmin) apiToggle.checked = false;
  }
  const titleText = $("#modal-title");
  const titleInput = $("#modal-title-input");
  const categoryLine = $("#modal-category");
  if (titleText && titleInput) {
    titleText.classList.toggle("hidden", isAdmin);
    titleInput.readOnly = !isAdmin;
  }
  if (categoryLine) categoryLine.classList.toggle("hidden", isAdmin);
  ["#modal-zh", "#modal-en"].forEach((selector) => {
    const field = $(selector);
    if (field) field.readOnly = !isAdmin;
  });
}

async function loadMe() {
  const response = await fetch("/api/auth/me");
  const data = await response.json();
  setUser(data.user);
  return data.user;
}

async function postForm(url, form) {
  const response = await fetch(url, { method: "POST", body: form });
  const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text();
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("请先登录");
  }
  if (!response.ok) throw new Error(data.detail || data || "请求失败");
  return data;
}

$("#prompt-categories").addEventListener("click", (event) => {
  const button = event.target.closest(".category-btn");
  if (!button) return;
  activeCategory = button.dataset.category;
  renderCategories();
  fetchPrompts();
});

$("#prompt-model-filters").addEventListener("click", (event) => {
  const button = event.target.closest(".model-filter");
  if (!button) return;
  activeModel = button.dataset.model;
  renderModelFilters();
  fetchPrompts();
});

$("#prompt-search").addEventListener("input", () => {
  currentSearch = $("#prompt-search").value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(fetchPrompts, 260);
});

$("#prompt-search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  currentSearch = $("#prompt-search").value.trim();
  clearTimeout(searchTimer);
  fetchPrompts();
});

function fillPromptModal(statusText = "") {
  activePromptLanguage = "zh";
  $("#modal-title").textContent = currentPrompt.title;
  $("#modal-title-input").value = currentPrompt.title;
  $("#modal-category").textContent = promptTaxonomyText(currentPrompt);
  $("#modal-category-input").value = currentPrompt.category || "";
  $("#modal-tags-input").value = (currentPrompt.tags || []).join("，");
  $("#modal-sort-input").value = currentPrompt.sort_order || "";
  $("#modal-ad-url").value = currentPrompt.url || "";
  $("#modal-ad-description").value = currentPrompt.description || "";
  $("#modal-ad-cta").value = currentPrompt.cta || "查看详情";
  $("#modal-zh").value = currentPrompt.zh || "";
  $("#modal-en").value = currentPrompt.en || "";
  renderPromptLanguageTabs();
  renderModalModelTags();
  renderModalImage();
  setFavoriteButton($("#modal-favorite"), Boolean(currentPrompt.favorited));
  $("#modal-favorite").dataset.promptId = currentPrompt.prompt_id || currentPrompt._index || "";
  $("#modal-favorite").classList.toggle("hidden", isAdItem(currentPrompt));
  updatePromptAdminControls();
  setPromptSaveText(currentPromptIndex < 0 ? (isAdItem(currentPrompt) ? "插入广告" : "发布到图库") : "保存修改");
  setPromptBusy(false);
  $("#modal-translate-status").textContent = statusText;
  $("#prompt-modal").hidden = false;
}

$("#prompt-new").addEventListener("click", () => {
  if (!currentUser?.is_prompt_admin) return;
  currentPromptIndex = -1;
  currentPromptId = "";
  promptDraftNonce = createPromptNonce();
  currentPrompt = {
    kind: "prompt",
    title: "未命名提示词",
    category: "未分类",
    tags: [],
    models: [],
    gradient: "from-slate-950 via-slate-700 to-orange-500",
    zh: "",
    en: "",
    image: ""
  };
  pendingPromptImageFile = null;
  fillPromptModal("请上传案例图，填写标题和提示词内容后发布。");
});

$("#ad-new").addEventListener("click", () => {
  if (!currentUser?.is_prompt_admin) return;
  currentPromptIndex = -1;
  currentPromptId = "";
  promptDraftNonce = createPromptNonce();
  currentPrompt = {
    kind: "ad",
    title: "广告标题",
    category: "广告",
    tags: ["广告"],
    models: [],
    gradient: "from-orange-600 via-amber-400 to-rose-500",
    zh: "",
    en: "",
    description: "",
    url: "",
    cta: "查看详情",
    sort_order: 0,
    image: ""
  };
  pendingPromptImageFile = null;
  fillPromptModal("请上传广告图，填写标题、说明和跳转链接后插入到图库。");
});

$("#prompt-gallery").addEventListener("click", (event) => {
  const favoriteButton = event.target.closest(".favorite-prompt");
  if (favoriteButton) {
    event.preventDefault();
    event.stopPropagation();
    togglePromptFavorite(favoriteButton.dataset.promptId, favoriteButton);
    return;
  }
  const button = event.target.closest(".prompt-open");
  if (!button) return;
  currentPromptIndex = Number(button.dataset.index);
  currentPromptId = button.dataset.id || "";
  const arrayIndex = currentPromptId ? promptArrayIndexFromId(currentPromptId) : promptArrayIndexFromServer(currentPromptIndex);
  if (arrayIndex < 0) return;
  const source = prompts[arrayIndex];
  currentPrompt = {
    ...source,
    tags: [...(source.tags || [])],
    models: [...(source.models || [])]
  };
  currentPromptId = promptItemId(source, arrayIndex);
  promptDraftNonce = "";
  pendingPromptImageFile = null;
  fillPromptModal();
});

$("#modal-close").addEventListener("click", () => { $("#prompt-modal").hidden = true; });
$("#modal-favorite")?.addEventListener("click", () => {
  togglePromptFavorite($("#modal-favorite").dataset.promptId, $("#modal-favorite"));
});

function renderModalImage() {
  const image = currentPrompt?.image;
  $("#modal-image-empty").classList.toggle("hidden", Boolean(image));
  $("#modal-image").classList.toggle("hidden", !image);
  if (image) $("#modal-image").src = image;
}

function renderModalModelTags() {
  const selected = new Set(currentPrompt?.models || []);
  $("#modal-model-tags").innerHTML = [...selected].map((model) => `
    <span class="rounded-full bg-cyan-400/15 px-3 py-1 text-xs font-black text-cyan-100 ring-1 ring-cyan-300/20">${model}</span>
  `).join("");
  $("#modal-model-selector").innerHTML = imageModels.map((model) => `
    <label class="cursor-pointer rounded-full px-3 py-2 text-sm font-bold ring-1 ${selected.has(model) ? "bg-emerald-500 text-white ring-emerald-300" : "bg-white/5 text-slate-300 ring-white/10"}">
      <input class="model-choice sr-only" type="checkbox" value="${model}" ${selected.has(model) ? "checked" : ""}>
      ${model}
    </label>
  `).join("");
}

function syncCurrentModels() {
  if (!currentPrompt) return;
  currentPrompt.models = [...document.querySelectorAll(".model-choice:checked")].map((input) => input.value);
  $("#modal-translate-status").textContent = "模型标签已修改，点击“发布到图库/保存修改”后生效。";
  renderModalModelTags();
  renderModelFilters();
  renderGallery();
}

function syncCurrentPrompt() {
  if (!currentPrompt) return;
  if (currentUser?.is_prompt_admin) {
    const title = $("#modal-title-input").value.trim() || "未命名提示词";
    currentPrompt.title = title;
    $("#modal-title").textContent = title;
    currentPrompt.category = $("#modal-category-input").value.trim() || (isAdItem(currentPrompt) ? "广告" : "未分类");
    currentPrompt.tags = parsePromptTags($("#modal-tags-input").value);
    currentPrompt.sort_order = Number($("#modal-sort-input").value || 0) || 0;
    if (isAdItem(currentPrompt)) {
      currentPrompt.url = $("#modal-ad-url").value.trim();
      currentPrompt.description = $("#modal-ad-description").value.trim();
      currentPrompt.cta = $("#modal-ad-cta").value.trim() || "查看详情";
    }
    $("#modal-category").textContent = promptTaxonomyText(currentPrompt);
  }
  if (!isAdItem(currentPrompt)) {
    currentPrompt.zh = $("#modal-zh").value.trim();
    currentPrompt.en = $("#modal-en").value.trim();
  }
  if (currentUser?.is_prompt_admin) $("#modal-translate-status").textContent = "内容已修改，点击“发布到图库/保存修改”后生效。";
  renderGallery();
}

$("#modal-model-selector").addEventListener("change", syncCurrentModels);

document.querySelectorAll("[data-copy-modal]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!currentPrompt) return;
    syncCurrentPrompt();
    const text = button.dataset.copyModal === "zh" ? currentPrompt.zh : currentPrompt.en;
    await navigator.clipboard.writeText(text);
    setCopyButtonState(button, true);
    setTimeout(() => setCopyButtonState(button, false), 1500);
  });
});

document.querySelectorAll("[data-prompt-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    activePromptLanguage = button.dataset.promptTab || "zh";
    renderPromptLanguageTabs();
  });
});

$("#modal-image-upload").addEventListener("change", () => {
  if (!currentUser?.is_prompt_admin) {
    $("#modal-translate-status").textContent = "只有提示词管理员可以上传案例图。";
    return;
  }
  const file = $("#modal-image-upload").files[0];
  if (!file || !currentPrompt) return;
  pendingPromptImageFile = file;
  currentPrompt.image = URL.createObjectURL(file);
  $("#modal-translate-status").textContent = "图片已选择，点击“发布到图库/保存修改”后会保存到服务器。";
  renderModalImage();
  renderGallery();
});

async function saveCurrentPrompt() {
  if (promptSaveInFlight) return;
  if (!currentUser?.is_prompt_admin || !currentPrompt) {
    $("#modal-translate-status").textContent = "只有后台授权的发布账号可以发布提示词。";
    return;
  }
  syncCurrentPrompt();
  const isCreate = currentPromptIndex < 0;
  if (isCreate && !promptDraftNonce) promptDraftNonce = createPromptNonce();
  const form = new FormData();
  form.append("kind", currentPrompt.kind || "prompt");
  form.append("title", currentPrompt.title);
  form.append("category", currentPrompt.category || "");
  form.append("tags", (currentPrompt.tags || []).join(","));
  form.append("zh", currentPrompt.zh || "");
  form.append("en", currentPrompt.en || "");
  form.append("description", currentPrompt.description || "");
  form.append("url", currentPrompt.url || "");
  form.append("cta", currentPrompt.cta || "");
  form.append("sort_order", currentPrompt.sort_order || "");
  form.append("models", (currentPrompt.models || []).join(","));
  if (isCreate) form.append("client_nonce", promptDraftNonce);
  if (pendingPromptImageFile) form.append("image", pendingPromptImageFile);
  $("#modal-translate-status").textContent = "正在保存到服务器...";
  setPromptSaveText("保存中...");
  setPromptBusy(true);
  try {
    const url = isCreate ? "/api/prompts/gallery" : promptMutationEndpoint();
    await postForm(url, form);
    pendingPromptImageFile = null;
    promptDraftNonce = "";
    await loadPromptGallery();
    $("#modal-translate-status").textContent = "已保存到服务器。";
    $("#prompt-modal").hidden = true;
  } catch (error) {
    $("#modal-translate-status").textContent = error.message;
    setPromptSaveText(currentPromptIndex < 0 ? (isAdItem(currentPrompt) ? "插入广告" : "发布到图库") : "保存修改");
    setPromptBusy(false);
  }
}

document.querySelectorAll("[data-prompt-save]").forEach((button) => {
  button.addEventListener("click", saveCurrentPrompt);
});

async function deleteCurrentPrompt() {
  if (!currentUser?.is_prompt_admin || !currentPrompt || currentPromptIndex < 0) {
    $("#modal-translate-status").textContent = "只有后台授权的发布账号可以下架或删除卡片。";
    return;
  }
  const action = isDefaultPromptSelection() ? "下架" : "删除";
  const ok = window.confirm(`确定要${action}「${currentPrompt.title || "未命名卡片"}」吗？`);
  if (!ok) return;
  $("#modal-translate-status").textContent = `正在${action}...`;
  try {
    const response = await fetch(promptMutationEndpoint(), { method: "DELETE" });
    const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) throw new Error(data.detail || data || `${action}失败`);
    pendingPromptImageFile = null;
    await loadPromptGallery();
    $("#prompt-modal").hidden = true;
  } catch (error) {
    $("#modal-translate-status").textContent = error.message;
  }
}

$("#modal-delete")?.addEventListener("click", deleteCurrentPrompt);

async function translateModalPrompt(target) {
  if (!currentPrompt) return;
  const source = target === "en" ? $("#modal-zh").value.trim() : $("#modal-en").value.trim();
  if (!source) {
    $("#modal-translate-status").textContent = target === "en" ? "请先填写中文 Prompt。" : "请先填写英文 Prompt。";
    return;
  }
  const user = await loadMe();
  if (!user) {
    $("#auth-modal").hidden = false;
    $("#modal-translate-status").textContent = "请先登录后再使用提示词翻译。";
    return;
  }
  const form = new FormData();
  form.append("text", source);
  form.append("target", target);
  form.append("use_api", $("#modal-use-api").checked ? "true" : "false");
  $("#modal-translate-status").textContent = "正在转换...";
  try {
    const data = await postForm("/api/prompt/translate", form);
    await loadMe();
    if (target === "en") {
      $("#modal-en").value = data.text;
      activePromptLanguage = "en";
    } else {
      $("#modal-zh").value = data.text;
      activePromptLanguage = "zh";
    }
    syncCurrentPrompt();
    renderPromptLanguageTabs();
    $("#modal-translate-status").textContent = data.provider === "local-fallback" ? "已用本地兜底转换。" : `已用后台 API 转换：${data.provider}`;
  } catch (error) {
    $("#modal-translate-status").textContent = error.message;
  }
}

$("#modal-to-en").addEventListener("click", () => translateModalPrompt("en"));
$("#modal-to-zh").addEventListener("click", () => translateModalPrompt("zh"));
$("#modal-title-input").addEventListener("input", syncCurrentPrompt);
$("#modal-category-input").addEventListener("input", syncCurrentPrompt);
$("#modal-tags-input").addEventListener("input", syncCurrentPrompt);
$("#modal-sort-input").addEventListener("input", syncCurrentPrompt);
$("#modal-ad-url").addEventListener("input", syncCurrentPrompt);
$("#modal-ad-description").addEventListener("input", syncCurrentPrompt);
$("#modal-ad-cta").addEventListener("input", syncCurrentPrompt);
$("#modal-zh").addEventListener("input", syncCurrentPrompt);
$("#modal-en").addEventListener("input", syncCurrentPrompt);

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
    await loadPromptGallery();
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

loadPromptGallery();
loadMe();
