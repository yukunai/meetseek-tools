const $ = (selector) => document.querySelector(selector);
let cachedUsers = [];
let cachedAiConfigs = {};
let cachedPromptPresets = {};

function adminHeaders() {
  return {};
}

function showAdmin(html) {
  const box = $("#admin-message");
  box.hidden = false;
  box.classList.remove("hidden");
  box.innerHTML = html;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const adLayouts = {
  banner: { label: "1 个横幅", count: 1, preview: "h-20" },
  split: { label: "2 个小横幅", count: 2, preview: "h-16" },
  grid4: { label: "4 个豆腐块", count: 4, preview: "h-14" },
};

function adItemCount(layout) {
  return adLayouts[layout]?.count || 1;
}

function activateSection(name) {
  document.querySelectorAll(".admin-section").forEach((section) => {
    section.classList.toggle("is-active", section.id === `section-${name}`);
  });
  document.querySelectorAll(".admin-nav").forEach((button) => {
    const active = button.dataset.adminSection === name;
    button.classList.toggle("is-active", active);
    button.classList.toggle("text-slate-700", !active);
    button.classList.toggle("hover:bg-slate-100", !active);
  });
}

document.querySelectorAll(".admin-nav").forEach((button) => {
  button.addEventListener("click", () => activateSection(button.dataset.adminSection));
});

$("#user-search").addEventListener("input", () => renderUsers(cachedUsers));

function renderAdManager(ads) {
  const box = $("#ad-manager");
  box.innerHTML = Object.entries(ads || {}).map(([slot, config]) => {
    const layout = adLayouts[config.layout] ? config.layout : "banner";
    const count = adItemCount(layout);
    const items = Array.from({ length: count }, (_, index) => (config.items || [])[index] || (index === 0 ? { html: config.html || "" } : { html: "" }));
    const previewCells = items.map((item, index) => `
      <div class="grid ${adLayouts[layout].preview} place-items-center rounded-lg border border-dashed ${item.html ? "border-orange-300 bg-orange-50 text-orange-700" : "border-slate-300 bg-white text-slate-400"} px-3 text-xs font-black">
        ${layout === "banner" ? "横幅广告" : layout === "split" ? `小横幅 ${index + 1}` : `豆腐块 ${index + 1}`}
      </div>
    `).join("");
    return `
    <div class="ad-card rounded-xl border border-slate-200 bg-slate-50 p-4" data-slot="${slot}" data-label="${escapeHtml(config.label || slot)}" data-note="${escapeHtml(config.note || "")}">
      <div class="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div>
          <b>${config.label}</b>
          <p class="text-xs text-slate-500">${slot} · ${config.note || ""}</p>
        </div>
        <label class="flex items-center gap-2 text-sm font-bold"><input class="ad-enabled" data-slot="${slot}" type="checkbox" ${config.enabled ? "checked" : ""}> 启用</label>
      </div>
      <label class="mb-3 block text-sm font-bold text-slate-700">
        广告版式
        <select class="ad-layout mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3" data-slot="${slot}">
          ${Object.entries(adLayouts).map(([key, meta]) => `<option value="${key}" ${key === layout ? "selected" : ""}>${meta.label}</option>`).join("")}
        </select>
      </label>
      <div class="grid gap-3 ${layout === "grid4" ? "md:grid-cols-2" : layout === "split" ? "md:grid-cols-2" : ""}">
        ${items.map((item, index) => `
          <label class="block text-sm font-bold text-slate-700">
            ${layout === "banner" ? "横幅广告代码" : layout === "split" ? `小横幅 ${index + 1} 代码` : `豆腐块 ${index + 1} 代码`}
            <textarea class="ad-html mt-2 min-h-28 w-full rounded-xl border border-slate-300 bg-white p-3 font-mono text-xs" data-slot="${slot}" data-index="${index}" placeholder="粘贴 Google AdSense 或自建广告 HTML">${escapeHtml(item.html || "")}</textarea>
          </label>
        `).join("")}
      </div>
      <div class="mt-3 rounded-xl border border-dashed border-slate-300 bg-white p-3 text-xs text-slate-500">
        <b>前端位置预览：</b>${config.label}
        <div class="mt-3 grid gap-2 ${layout === "grid4" ? "grid-cols-2 md:grid-cols-4" : layout === "split" ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1"}">
          ${previewCells}
        </div>
      </div>
      <button class="save-ad mt-3 rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white" data-slot="${slot}" type="button">保存这个广告位</button>
    </div>
  `;
  }).join("");
}

function renderLinkCardConfig(config) {
  $("#link-card-whitelist").value = (config?.whitelist || []).join("\n");
  $("#link-card-blacklist").value = (config?.blacklist || []).join("\n");
  $("#link-card-status").textContent = "白名单生成卡片；黑名单直接屏蔽。";
}

function renderPromptConfig(configs, adminEmails = []) {
  cachedAiConfigs = configs || {};
  const keys = Object.keys(cachedAiConfigs);
  const selected = $("#prompt-config-key").value || keys[0] || "image_prompt_reverse";
  $("#prompt-config-key").innerHTML = keys.map((key) => {
    const config = cachedAiConfigs[key] || {};
    return `<option value="${key}" ${key === selected ? "selected" : ""}>${config.label || key}</option>`;
  }).join("");
  $("#prompt-config-key").value = cachedAiConfigs[selected] ? selected : (keys[0] || "image_prompt_reverse");
  $("#prompt-admin-emails").value = (adminEmails || []).join(", ");
  renderCurrentPromptConfig();
}

function renderCurrentPromptConfig() {
  const key = $("#prompt-config-key").value;
  const config = cachedAiConfigs[key];
  if (!config) return;
  $("#prompt-provider").value = config.provider || "openai";
  $("#prompt-api-base").value = config.api_base || "";
  $("#prompt-model").value = config.model || "";
  $("#prompt-skill").value = config.skill || "";
  $("#prompt-api-key").value = "";
  $("#prompt-clear-key").checked = false;
  $("#prompt-kind-label").textContent = config.kind === "vision" ? "视觉模型配置" : "文本模型配置";
  $("#prompt-config-description").textContent = config.description || "";
  const preset = cachedPromptPresets[config.provider] || {};
  $("#prompt-provider-note").textContent = preset.note || "";
  const visionWarning = config.kind === "vision" && !config.vision_ready ? " · 当前模型不像视觉模型，请更换为 gpt-4o-mini / Gemini / Claude / Qwen-VL 等" : "";
  $("#prompt-config-status").textContent = `API Key：${config.api_key_source || "未知"} · ${config.api_key_set ? "已配置" : "未配置"}${visionWarning}`;
}

function renderPromptProviders(presets, selected) {
  cachedPromptPresets = presets || {};
  $("#prompt-provider").innerHTML = Object.entries(presets || {}).map(([key, preset]) => `
    <option value="${key}" ${key === selected ? "selected" : ""}>${preset.label}</option>
  `).join("");
  $("#prompt-provider").dataset.presets = JSON.stringify(presets || {});
}

function renderVideoUsageConfig(rules) {
  const single = rules?.video_download || {};
  const batch = rules?.video_batch || {};
  $("#video-single-free").value = single.free_limit ?? 10;
  $("#video-single-pro").value = single.pro_limit ?? 80;
  $("#video-single-vip").value = single.vip_limit ?? 300;
  $("#video-batch-free").value = batch.free_limit ?? 5;
  $("#video-batch-pro").value = batch.pro_limit ?? 30;
  $("#video-batch-vip").value = batch.vip_limit ?? 100;
  $("#video-config-status").textContent = "游客：0 次/天；下载会同时按积分规则扣分。";
}

function renderCreditRules(rules) {
  $("#credit-rules-manager").innerHTML = Object.entries(rules || {}).map(([key, rule]) => {
    const tiers = new Set(rule.tiers || []);
    return `
      <div class="rounded-xl bg-white p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <b>${rule.label}</b>
            <p class="text-xs text-slate-500">${rule.type || "积分规则"} · ${key}</p>
          </div>
          <label class="flex items-center gap-2 text-sm font-bold">
            <input class="credit-enabled" data-rule="${key}" type="checkbox" ${rule.enabled ? "checked" : ""}> 启用
          </label>
        </div>
        <div class="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_120px] md:items-end">
          <label class="text-sm font-bold text-slate-700">每次扣积分
            <input class="credit-cost mt-2 h-10 w-full rounded-xl border border-slate-200 px-3" data-rule="${key}" type="number" min="0" step="1" value="${rule.cost || 0}">
          </label>
          <div>
            <div class="mb-2 text-sm font-bold text-slate-700">可用会员等级</div>
            <div class="flex flex-wrap gap-3">
              ${["free", "pro", "vip"].map((tier) => `
                <label class="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-sm font-bold">
                  <input class="credit-tier" data-rule="${key}" type="checkbox" value="${tier}" ${tiers.has(tier) ? "checked" : ""}>
                  ${tier}
                </label>
              `).join("")}
            </div>
          </div>
          <button class="save-credit-rule rounded-xl bg-slate-950 px-4 py-2 font-bold text-white" data-rule="${key}" type="button">保存规则</button>
        </div>
      </div>
    `;
  }).join("");
}

function renderUsers(users) {
  const query = ($("#user-search")?.value || "").trim().toLowerCase();
  const filtered = query
    ? users.filter((user) => {
        const status = user.deleted_at ? "已删除 deleted" : user.disabled ? "已禁用 disabled" : "正常 active";
        const posting = user.posting_disabled ? "禁止发文 no post" : "允许发文 can post";
        const muted = user.muted_until && user.muted_until * 1000 > Date.now() ? "禁言 muted" : "未禁言 unmuted";
        const promptRole = user.is_prompt_admin ? "提示词发布者 publisher" : "普通会员 member";
        return [user.name, user.email, user.tier, status, posting, muted, promptRole, String(user.points || 0)].join(" ").toLowerCase().includes(query);
      })
    : users;
  $("#users-manager").innerHTML = filtered.length ? filtered.map((user) => `
    <div class="grid gap-3 rounded-xl ${user.deleted_at ? "bg-slate-100 opacity-60" : "bg-white"} p-3 md:grid-cols-[minmax(0,1fr)_260px_180px_180px_260px] md:items-center">
      <div>
        <b>${user.name}</b>
        <p class="text-slate-500">${user.email} · ${new Date(user.created_at * 1000).toLocaleString()}</p>
        <p class="mt-1 text-xs font-bold ${user.deleted_at ? "text-red-600" : user.disabled ? "text-orange-600" : "text-emerald-600"}">
          ${user.deleted_at ? `已删除 · ${new Date(user.deleted_at * 1000).toLocaleString()}` : user.disabled ? "已禁用" : "正常"}
          <span class="ml-2 ${user.is_prompt_admin ? "text-cyan-700" : "text-slate-400"}">${user.is_prompt_admin ? "可发布提示词" : "未开发布权限"}</span>
        </p>
        <p class="mt-1 text-xs font-bold text-slate-500">
          ${user.posting_disabled ? "禁止发文" : "可发文"}
          · ${user.muted_until && user.muted_until * 1000 > Date.now() ? `禁言至 ${new Date(user.muted_until * 1000).toLocaleString()}` : "未禁言"}
        </p>
      </div>
      <div class="grid grid-cols-3 gap-2">
        ${["free", "pro", "vip"].map((tier) => `
          <button class="set-tier rounded-xl px-3 py-2 text-sm font-bold ${user.tier === tier ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-700"}" data-user-id="${user.id}" data-tier="${tier}" type="button" ${user.deleted_at ? "disabled" : ""}>${tier}</button>
        `).join("")}
      </div>
      <div class="grid gap-2">
        <input class="user-points h-10 rounded-xl border border-slate-200 px-3" data-user-id="${user.id}" type="number" min="0" step="1" value="${user.points || 0}" aria-label="积分余额" ${user.deleted_at ? "disabled" : ""}>
        <div class="grid grid-cols-3 gap-2">
          <button class="adjust-points rounded-xl bg-emerald-50 px-2 py-2 text-sm font-bold text-emerald-700" data-user-id="${user.id}" data-delta="10" type="button" ${user.deleted_at ? "disabled" : ""}>+10</button>
          <button class="adjust-points rounded-xl bg-rose-50 px-2 py-2 text-sm font-bold text-rose-700" data-user-id="${user.id}" data-delta="-10" type="button" ${user.deleted_at ? "disabled" : ""}>-10</button>
          <button class="save-points rounded-xl bg-orange-600 px-2 py-2 text-sm font-bold text-white" data-user-id="${user.id}" type="button" ${user.deleted_at ? "disabled" : ""}>保存</button>
        </div>
      </div>
      <div class="grid gap-2">
        <input class="user-password h-10 rounded-xl border border-slate-200 px-3 text-sm" data-user-id="${user.id}" type="password" minlength="8" placeholder="新密码，至少 8 位" ${user.deleted_at ? "disabled" : ""}>
        <button class="save-password rounded-xl bg-slate-950 px-3 py-2 text-sm font-bold text-white" data-user-id="${user.id}" type="button" ${user.deleted_at ? "disabled" : ""}>改密码</button>
      </div>
      <div class="flex flex-wrap gap-2">
        ${user.deleted_at ? "" : `<button class="toggle-prompt-publisher rounded-xl ${user.is_prompt_admin ? "bg-cyan-50 text-cyan-800" : "bg-emerald-50 text-emerald-800"} px-3 py-2 text-sm font-bold" data-user-id="${user.id}" data-enabled="${user.is_prompt_admin ? "false" : "true"}" type="button">${user.is_prompt_admin ? "取消发布" : "授权发布"}</button>`}
        ${user.deleted_at ? "" : `<button class="toggle-posting rounded-xl ${user.posting_disabled ? "bg-orange-50 text-orange-800" : "bg-slate-100 text-slate-700"} px-3 py-2 text-sm font-bold" data-user-id="${user.id}" data-disabled="${user.posting_disabled ? "false" : "true"}" type="button">${user.posting_disabled ? "恢复发文" : "禁发"}</button>`}
        ${user.deleted_at ? "" : `<button class="mute-user rounded-xl ${user.muted_until && user.muted_until * 1000 > Date.now() ? "bg-orange-50 text-orange-800" : "bg-slate-100 text-slate-700"} px-3 py-2 text-sm font-bold" data-user-id="${user.id}" data-hours="${user.muted_until && user.muted_until * 1000 > Date.now() ? "0" : "24"}" type="button">${user.muted_until && user.muted_until * 1000 > Date.now() ? "解除禁言" : "禁言24h"}</button>`}
        ${user.deleted_at ? "" : `<button class="toggle-user rounded-xl bg-slate-100 px-3 py-2 text-sm font-bold text-slate-700" data-user-id="${user.id}" data-disabled="${user.disabled ? "false" : "true"}" type="button">${user.disabled ? "启用" : "禁用"}</button>`}
        ${user.deleted_at ? "" : `<button class="delete-user rounded-xl bg-red-50 px-3 py-2 text-sm font-bold text-red-700" data-user-id="${user.id}" type="button">删除</button>`}
      </div>
    </div>
  `).join("") : `<p>${query ? "没有匹配的会员。" : "暂无用户。"}</p>`;
}

function renderPaymentConfig(config) {
  if (!config) return;
  $("#payment-manual-enabled").checked = Boolean(config.manual_enabled);
  $("#payment-stripe-enabled").checked = Boolean(config.stripe_enabled);
  $("#payment-stripe-currency").value = config.stripe_currency || "usd";
  $("#payment-stripe-success").value = config.stripe_success_url || "";
  $("#payment-stripe-cancel").value = config.stripe_cancel_url || "";
  $("#payment-stripe-secret").value = "";
  $("#payment-stripe-webhook-secret").value = "";
  $("#payment-stripe-state").textContent = `Stripe Key：${config.stripe_secret_configured ? "已配置" : "未配置"} · Webhook Secret：${config.stripe_webhook_secret_configured ? "已配置" : "未配置"} · Webhook：${config.stripe_webhook_url || ""}`;
  $("#payment-xunhu-enabled").checked = Boolean(config.xunhu_enabled);
  $("#payment-xunhu-appid").value = config.xunhu_appid || "";
  $("#payment-xunhu-appsecret").value = "";
  $("#payment-xunhu-gateway").value = config.xunhu_gateway || "https://api.xunhupay.com/payment/do.html";
  $("#payment-xunhu-notify").value = config.xunhu_notify_url || "";
  $("#payment-xunhu-return").value = config.xunhu_return_url || "";
  $("#payment-xunhu-callback").value = config.xunhu_callback_url || "";
  $("#payment-xunhu-state").textContent = `APPID：${config.xunhu_appid_configured ? "已配置" : "未配置"} · APPSECRET：${config.xunhu_appsecret_configured ? "已配置" : "未配置"} · 异步通知：${config.xunhu_notify_url || ""}`;
  $("#payment-instructions").value = config.instructions || "";
  $("#payment-packages").value = JSON.stringify(config.packages || [], null, 2);
}

function renderPaymentOrders(orders) {
  const methodLabel = { wechat: "微信", alipay: "支付宝", stripe: "Stripe", xunhupay: "虎皮椒" };
  $("#payment-orders-manager").innerHTML = orders.length ? orders.map((order) => `
    <div class="rounded-xl bg-white p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <b>${order.package_name}</b>
          <p class="text-slate-500">${order.email} · ${methodLabel[order.method] || order.method} · ${new Date(order.created_at * 1000).toLocaleString()}</p>
          <p class="mt-1">金额 ${order.amount} 元 · ${order.points} 积分 · 状态：${order.status}</p>
          <p class="mt-1 text-slate-500">单号：${order.transaction_no || "未填写"} ${order.screenshot ? `· <a class="text-orange-600" href="${order.screenshot}" target="_blank">查看截图</a>` : ""}</p>
        </div>
        ${order.status === "pending" ? `
          <div class="flex gap-2">
            <button class="approve-order rounded-xl bg-emerald-600 px-4 py-2 font-bold text-white" data-order-id="${order.id}" type="button">通过并加分</button>
            <button class="reject-order rounded-xl bg-slate-100 px-4 py-2 font-bold text-slate-700" data-order-id="${order.id}" type="button">驳回</button>
          </div>
        ` : ""}
      </div>
    </div>
  `).join("") : "<p>暂无充值订单。</p>";
}

function renderUsageRules(rules) {
  $("#usage-rules-manager").innerHTML = Object.entries(rules || {}).map(([key, rule]) => `
    <div class="rounded-xl bg-white p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <b>${rule.label}</b>
          <p class="text-xs text-slate-500">${key}</p>
        </div>
        <label class="flex items-center gap-2 text-sm font-bold"><input class="usage-enabled" data-rule="${key}" type="checkbox" ${rule.enabled ? "checked" : ""}> 启用限制</label>
      </div>
      <div class="grid gap-3 md:grid-cols-5 md:items-end">
        ${["guest", "free", "pro", "vip"].map((tier) => `
          <label class="text-sm font-bold text-slate-700">${tier} 每日
            <input class="usage-limit mt-2 h-10 w-full rounded-xl border border-slate-200 px-3" data-rule="${key}" data-tier="${tier}" type="number" step="1" value="${rule[`${tier}_limit`]}">
          </label>
        `).join("")}
        <button class="save-usage-rule rounded-xl bg-slate-950 px-4 py-2 font-bold text-white" data-rule="${key}" type="button">保存限制</button>
      </div>
    </div>
  `).join("");
}

function renderRewardConfig(config) {
  if (!config) return;
  $("#reward-enabled").checked = Boolean(config.enabled);
  $("#reward-seconds").value = config.seconds || 30;
  $("#reward-points").value = config.points || 1;
  $("#reward-daily-limit").value = config.daily_limit || 5;
  $("#reward-title").value = config.title || "看广告赚积分";
  $("#reward-description").value = config.description || "";
}

function renderCheckinConfig(config, records = []) {
  if (!config) return;
  $("#checkin-enabled").checked = Boolean(config.enabled);
  $("#checkin-points").value = config.points || 0;
  $("#checkin-streak-days").value = config.streak_days || 7;
  $("#checkin-streak-bonus").value = config.streak_bonus || 0;
  $("#checkin-title").value = config.title || "每日签到";
  $("#checkin-description").value = config.description || "";
  $("#checkin-records").innerHTML = records.length ? records.map((item) => `
    <div class="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white p-3">
      <span><b>${item.name}</b> · ${item.email} · ${item.day}</span>
      <span class="font-bold text-orange-600">+${item.points} · 连续 ${item.streak} 天</span>
    </div>
  `).join("") : "<p>暂无签到记录。</p>";
}

function collapsibleLog(title, summary, items, emptyText) {
  return `
    <details class="rounded-xl border border-slate-200 bg-white p-3">
      <summary class="cursor-pointer select-none font-bold">
        ${title}
        <span class="ml-2 text-xs font-normal text-slate-500">${summary}</span>
      </summary>
      <div class="mt-3 max-h-96 overflow-auto rounded-lg bg-slate-50 p-3 text-sm leading-6">
        ${items.length ? items.join("") : `<p>${emptyText}</p>`}
      </div>
    </details>
  `;
}

async function loadAdmin() {
  const response = await fetch("/api/admin/status", { headers: adminHeaders() });
  const data = await response.json();
  if (response.status === 401) {
    location.href = "/admin";
    return;
  }
  if (!response.ok) throw new Error(data.detail || "后台读取失败");
  const usersResponse = await fetch("/api/admin/users", { headers: adminHeaders() });
  const usersData = await usersResponse.json();
  if (!usersResponse.ok) throw new Error(usersData.detail || "用户读取失败");
  const ordersResponse = await fetch("/api/admin/payment-orders", { headers: adminHeaders() });
  const ordersData = await ordersResponse.json();
  if (!ordersResponse.ok) throw new Error(ordersData.detail || "充值订单读取失败");
  renderAdManager(data.ads);
  renderLinkCardConfig(data.link_card_config || {});
  renderPromptProviders(data.prompt_provider_presets, data.prompt_config?.provider || "openai");
  renderPromptConfig(data.ai_configs || { image_prompt_reverse: data.prompt_config }, data.prompt_admin_emails || []);
  renderCreditRules(data.credit_rules);
  renderUsageRules(data.usage_rules);
  renderVideoUsageConfig(data.usage_rules);
  renderPaymentConfig(data.payment_config);
  renderPaymentOrders(ordersData.orders || []);
  renderRewardConfig(data.reward_config);
  renderCheckinConfig(data.checkin_config, data.checkins || []);
  cachedUsers = usersData.users || [];
  renderUsers(cachedUsers);
  const visitorItems = data.visitors.recent.map((visit) => `<p>${new Date(visit.time * 1000).toLocaleString()} · ${visit.ip}</p>`);
  const resetItems = (data.password_resets || []).map((reset) => {
    const expired = reset.expires_at * 1000 < Date.now();
    const status = reset.used_at ? "已使用" : expired ? "已过期" : "可用";
    return `<p class="mb-3 border-b border-slate-200 pb-3">
      ${new Date(reset.created_at * 1000).toLocaleString()} · ${reset.email} · ${status}<br>
      <a class="break-all font-bold text-orange-600" href="${reset.reset_link}" target="_blank">${reset.reset_link}</a>
    </p>`;
  });
  const logItems = data.logs.map((log) => `<p class="mb-2">${new Date(log.time * 1000).toLocaleString()} · ${log.level} · ${log.message}${log.email ? ` · ${log.email}` : ""}${log.reset_link ? `<br><a class="break-all font-bold text-orange-600" href="${log.reset_link}" target="_blank">${log.reset_link}</a>` : ""}</p>`);
  $("#overview-content").innerHTML = `
    <div class="grid gap-4">
      <div class="grid gap-3 md:grid-cols-6">
        <div class="rounded-xl bg-white p-3"><b>下载目录</b><p>${data.disk.downloads || "0 B"}</p></div>
        <div class="rounded-xl bg-white p-3"><b>图片目录</b><p>${data.disk.images || "0 B"}</p></div>
        <div class="rounded-xl bg-white p-3"><b>压缩目录</b><p>${data.disk.compressed || "0 B"}</p></div>
        <div class="rounded-xl bg-white p-3"><b>办公目录</b><p>${data.disk.office || "0 B"}</p></div>
        <div class="rounded-xl bg-white p-3"><b>充值凭证</b><p>${data.disk.payments || "0 B"}</p></div>
        <div class="rounded-xl bg-white p-3"><b>临时目录</b><p>${data.disk.tmp || "0 B"}</p></div>
      </div>
      <div class="grid gap-3 md:grid-cols-4">
        <div class="rounded-xl bg-white p-3"><b>今日访问</b><p>${data.visitors.today.views}</p></div>
        <div class="rounded-xl bg-white p-3"><b>本月访问</b><p>${data.visitors.month.views}</p></div>
        <div class="rounded-xl bg-white p-3"><b>本月访客</b><p>${data.visitors.month.visitors}</p></div>
        <div class="rounded-xl bg-white p-3"><b>累计访问</b><p>${data.visitors.total}</p></div>
      </div>
    </div>
  `;
  $("#logs-content").innerHTML = `
    <div class="grid gap-4">
      <div class="rounded-xl bg-white p-3"><b>当前任务</b>${data.tasks.length ? data.tasks.map((task) => `<p>${task.id} · ${task.status} · ${task.title || "未命名"}</p>`).join("") : "<p>暂无任务</p>"}</div>
      <div class="mt-2 grid gap-3">
        ${collapsibleLog("最近访客", `共 ${data.visitors.recent.length} 条，点击展开`, visitorItems, "暂无记录")}
        ${collapsibleLog("密码重置链接", `共 ${(data.password_resets || []).length} 条，点击展开`, resetItems, "暂无重置请求")}
        ${collapsibleLog("最近日志", `共 ${data.logs.length} 条，点击展开`, logItems, "暂无日志")}
      </div>
    </div>
  `;
  showAdmin("<p>后台数据已刷新。</p>");
}

$("#admin-logout").addEventListener("click", async () => {
  await fetch("/api/admin/logout", { method: "POST" });
  location.href = "/admin";
});

$("#admin-refresh").addEventListener("click", async () => {
  try {
    await loadAdmin();
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#admin-cleanup").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/admin/cleanup", { method: "POST", headers: adminHeaders() });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "清理失败");
    showAdmin(`<p>已清理 ${data.removed} 个文件。</p>`);
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

document.querySelectorAll(".feature-toggle").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const statusResponse = await fetch("/api/admin/status", { headers: adminHeaders() });
      const status = await statusResponse.json();
      if (!statusResponse.ok) throw new Error(status.detail || "后台读取失败");
      const name = button.dataset.feature;
      const form = new FormData();
      form.append("name", name);
      form.append("enabled", status.features?.[name] ? "false" : "true");
      const response = await fetch("/api/admin/features", { method: "POST", headers: adminHeaders(), body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "更新失败");
      showAdmin(`<p>工具开关已更新：${name} = ${data.features[name]}</p>`);
    } catch (error) {
      showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
    }
  });
});

$("#video-usage-save").addEventListener("click", async () => {
  const form = new FormData();
  form.append("single_free", $("#video-single-free").value);
  form.append("single_pro", $("#video-single-pro").value);
  form.append("single_vip", $("#video-single-vip").value);
  form.append("batch_free", $("#video-batch-free").value);
  form.append("batch_pro", $("#video-batch-pro").value);
  form.append("batch_vip", $("#video-batch-vip").value);
  try {
    const response = await fetch("/api/admin/video-usage-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderUsageRules(data.usage_rules);
    renderVideoUsageConfig(data.usage_rules);
    showAdmin("<p>视频下载次数限制已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#prompt-save").addEventListener("click", async () => {
  const form = new FormData();
  form.append("config_key", $("#prompt-config-key").value);
  form.append("provider", $("#prompt-provider").value);
  form.append("api_base", $("#prompt-api-base").value.trim());
  form.append("model", $("#prompt-model").value.trim());
  form.append("api_key", $("#prompt-api-key").value.trim());
  form.append("clear_api_key", $("#prompt-clear-key").checked ? "true" : "false");
  form.append("skill", $("#prompt-skill").value.trim());
  form.append("admin_emails", $("#prompt-admin-emails").value.trim());
  try {
    const response = await fetch("/api/admin/prompt-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderPromptConfig(data.ai_configs || { image_prompt_reverse: data.prompt_config }, data.prompt_admin_emails || []);
    showAdmin("<p>AI API 配置已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#prompt-config-key").addEventListener("change", renderCurrentPromptConfig);

$("#prompt-provider").addEventListener("change", () => {
  const presets = JSON.parse($("#prompt-provider").dataset.presets || "{}");
  const preset = presets[$("#prompt-provider").value];
  if (!preset) return;
  const config = cachedAiConfigs[$("#prompt-config-key").value] || {};
  $("#prompt-api-base").value = preset.api_base || "";
  $("#prompt-model").value = config.kind === "vision" ? (preset.vision_model || preset.model || "") : (preset.text_model || preset.model || "");
  $("#prompt-provider-note").textContent = preset.note || "";
});

$("#prompt-test").addEventListener("click", async () => {
  try {
    const form = new FormData();
    form.append("config_key", $("#prompt-config-key").value);
    form.append("provider", $("#prompt-provider").value);
    form.append("api_base", $("#prompt-api-base").value.trim());
    form.append("model", $("#prompt-model").value.trim());
    form.append("api_key", $("#prompt-api-key").value.trim());
    form.append("skill", $("#prompt-skill").value.trim());
    const response = await fetch("/api/admin/prompt-test", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "测试失败");
    showAdmin(data.ok
      ? `<p>连接成功：${data.provider} / ${data.model} · 返回：${data.sample}${data.warning ? `<br><span class="text-orange-600">${data.warning}</span>` : ""}</p>`
      : `<p class="text-red-600">连接失败：${data.provider} / ${data.model} · ${data.error}</p>`);
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#users-manager").addEventListener("click", async (event) => {
  const tierButton = event.target.closest(".set-tier");
  const pointsButton = event.target.closest(".save-points");
  const adjustPointsButton = event.target.closest(".adjust-points");
  const passwordButton = event.target.closest(".save-password");
  const promptPublisherButton = event.target.closest(".toggle-prompt-publisher");
  const postingButton = event.target.closest(".toggle-posting");
  const muteButton = event.target.closest(".mute-user");
  const toggleButton = event.target.closest(".toggle-user");
  const deleteButton = event.target.closest(".delete-user");
  if (!tierButton && !pointsButton && !adjustPointsButton && !passwordButton && !promptPublisherButton && !postingButton && !muteButton && !toggleButton && !deleteButton) return;
  const userId = (tierButton || pointsButton || adjustPointsButton || passwordButton || promptPublisherButton || postingButton || muteButton || toggleButton || deleteButton).dataset.userId;
  const form = new FormData();
  try {
    if (deleteButton && !confirm("确认删除这个用户吗？删除后会禁用账号并清掉登录会话，但保留充值记录。")) return;
    if (passwordButton && !confirm("确认修改这个用户的登录密码吗？修改后会退出该用户现有登录状态。")) return;
    form.append("user_id", userId);
    let endpoint = "/api/admin/users/tier";
    if (tierButton) {
      form.append("tier", tierButton.dataset.tier);
    } else if (pointsButton) {
      endpoint = "/api/admin/users/points";
      form.append("points", document.querySelector(`.user-points[data-user-id="${userId}"]`).value);
    } else if (adjustPointsButton) {
      endpoint = "/api/admin/users/points-adjust";
      form.append("delta", adjustPointsButton.dataset.delta);
    } else if (passwordButton) {
      endpoint = "/api/admin/users/password";
      form.append("password", document.querySelector(`.user-password[data-user-id="${userId}"]`).value);
    } else if (promptPublisherButton) {
      endpoint = "/api/admin/users/prompt-publisher";
      form.append("enabled", promptPublisherButton.dataset.enabled);
    } else if (postingButton) {
      endpoint = "/api/admin/users/posting";
      form.append("disabled", postingButton.dataset.disabled);
    } else if (muteButton) {
      endpoint = "/api/admin/users/mute";
      form.append("hours", muteButton.dataset.hours);
    } else if (toggleButton) {
      endpoint = "/api/admin/users/status";
      form.append("disabled", toggleButton.dataset.disabled);
    } else {
      endpoint = "/api/admin/users/delete";
    }
    const response = await fetch(endpoint, { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    showAdmin(`<p>${data.user.email} 已更新：${data.user.tier} 会员，${data.user.points} 积分。</p>`);
    await loadAdmin();
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#credit-rules-manager").addEventListener("click", async (event) => {
  const button = event.target.closest(".save-credit-rule");
  if (!button) return;
  const key = button.dataset.rule;
  const tiers = [...document.querySelectorAll(`.credit-tier[data-rule="${key}"]:checked`)].map((input) => input.value);
  const form = new FormData();
  form.append("key", key);
  form.append("enabled", document.querySelector(`.credit-enabled[data-rule="${key}"]`).checked ? "true" : "false");
  form.append("cost", document.querySelector(`.credit-cost[data-rule="${key}"]`).value);
  form.append("tiers", tiers.join(","));
  try {
    const response = await fetch("/api/admin/credit-rules", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderCreditRules(data.credit_rules);
    showAdmin("<p>积分规则已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#usage-rules-manager").addEventListener("click", async (event) => {
  const button = event.target.closest(".save-usage-rule");
  if (!button) return;
  const key = button.dataset.rule;
  const form = new FormData();
  form.append("key", key);
  form.append("enabled", document.querySelector(`.usage-enabled[data-rule="${key}"]`).checked ? "true" : "false");
  ["guest", "free", "pro", "vip"].forEach((tier) => {
    form.append(`${tier}_limit`, document.querySelector(`.usage-limit[data-rule="${key}"][data-tier="${tier}"]`).value);
  });
  try {
    const response = await fetch("/api/admin/usage-rules", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderUsageRules(data.usage_rules);
    showAdmin("<p>次数限制已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#payment-save").addEventListener("click", async () => {
  const form = new FormData();
  form.append("manual_enabled", $("#payment-manual-enabled").checked ? "true" : "false");
  form.append("stripe_enabled", $("#payment-stripe-enabled").checked ? "true" : "false");
  form.append("stripe_currency", $("#payment-stripe-currency").value.trim());
  form.append("stripe_secret_key", $("#payment-stripe-secret").value.trim());
  form.append("stripe_webhook_secret", $("#payment-stripe-webhook-secret").value.trim());
  form.append("stripe_success_url", $("#payment-stripe-success").value.trim());
  form.append("stripe_cancel_url", $("#payment-stripe-cancel").value.trim());
  form.append("xunhu_enabled", $("#payment-xunhu-enabled").checked ? "true" : "false");
  form.append("xunhu_appid", $("#payment-xunhu-appid").value.trim());
  form.append("xunhu_appsecret", $("#payment-xunhu-appsecret").value.trim());
  form.append("xunhu_gateway", $("#payment-xunhu-gateway").value.trim());
  form.append("xunhu_notify_url", $("#payment-xunhu-notify").value.trim());
  form.append("xunhu_return_url", $("#payment-xunhu-return").value.trim());
  form.append("xunhu_callback_url", $("#payment-xunhu-callback").value.trim());
  form.append("instructions", $("#payment-instructions").value.trim());
  form.append("packages_json", $("#payment-packages").value.trim());
  if ($("#payment-wechat-qr").files[0]) form.append("wechat_qr", $("#payment-wechat-qr").files[0]);
  if ($("#payment-alipay-qr").files[0]) form.append("alipay_qr", $("#payment-alipay-qr").files[0]);
  try {
    const response = await fetch("/api/admin/payment-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderPaymentConfig(data.payment_config);
    showAdmin("<p>充值配置已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#payment-orders-manager").addEventListener("click", async (event) => {
  const approve = event.target.closest(".approve-order");
  const reject = event.target.closest(".reject-order");
  if (!approve && !reject) return;
  const form = new FormData();
  form.append("order_id", (approve || reject).dataset.orderId);
  const endpoint = approve ? "/api/admin/payment-orders/approve" : "/api/admin/payment-orders/reject";
  try {
    const response = await fetch(endpoint, { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "操作失败");
    showAdmin(`<p>订单 ${data.order.id} 已更新：${data.order.status}</p>`);
    await loadAdmin();
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#reward-save").addEventListener("click", async () => {
  const form = new FormData();
  form.append("enabled", $("#reward-enabled").checked ? "true" : "false");
  form.append("seconds", $("#reward-seconds").value);
  form.append("points", $("#reward-points").value);
  form.append("daily_limit", $("#reward-daily-limit").value);
  form.append("title", $("#reward-title").value.trim());
  form.append("description", $("#reward-description").value.trim());
  try {
    const response = await fetch("/api/admin/reward-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderRewardConfig(data.reward_config);
    showAdmin("<p>广告积分规则已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#checkin-save").addEventListener("click", async () => {
  const form = new FormData();
  form.append("enabled", $("#checkin-enabled").checked ? "true" : "false");
  form.append("points", $("#checkin-points").value);
  form.append("streak_days", $("#checkin-streak-days").value);
  form.append("streak_bonus", $("#checkin-streak-bonus").value);
  form.append("title", $("#checkin-title").value.trim());
  form.append("description", $("#checkin-description").value.trim());
  try {
    const response = await fetch("/api/admin/checkin-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderCheckinConfig(data.checkin_config);
    showAdmin("<p>签到积分规则已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#ad-manager").addEventListener("click", async (event) => {
  const button = event.target.closest(".save-ad");
  if (!button) return;
  const slot = button.dataset.slot;
  const layout = document.querySelector(`.ad-layout[data-slot="${slot}"]`).value;
  const items = [...document.querySelectorAll(`.ad-html[data-slot="${slot}"]`)]
    .sort((a, b) => Number(a.dataset.index || 0) - Number(b.dataset.index || 0))
    .map((input) => ({ html: input.value }));
  const form = new FormData();
  form.append("slot", slot);
  form.append("enabled", document.querySelector(`.ad-enabled[data-slot="${slot}"]`).checked ? "true" : "false");
  form.append("layout", layout);
  form.append("html", items[0]?.html || "");
  form.append("items_json", JSON.stringify(items));
  try {
    const response = await fetch("/api/admin/ads", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderAdManager(data.ads);
    showAdmin("<p>广告位已保存。刷新工具箱页面后前端会按位置显示。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

$("#ad-manager").addEventListener("change", (event) => {
  const select = event.target.closest(".ad-layout");
  if (!select) return;
  const slot = select.dataset.slot;
  const currentAds = {};
  document.querySelectorAll(".ad-layout").forEach((layoutInput) => {
    const key = layoutInput.dataset.slot;
    const items = [...document.querySelectorAll(`.ad-html[data-slot="${key}"]`)]
      .sort((a, b) => Number(a.dataset.index || 0) - Number(b.dataset.index || 0))
      .map((input) => ({ html: input.value }));
    const card = layoutInput.closest(".ad-card");
    currentAds[key] = {
      label: card?.dataset.label || key,
      enabled: document.querySelector(`.ad-enabled[data-slot="${key}"]`)?.checked,
      layout: key === slot ? select.value : layoutInput.value,
      items,
      note: card?.dataset.note || "",
    };
  });
  renderAdManager(currentAds);
});

$("#link-card-save")?.addEventListener("click", async () => {
  const form = new FormData();
  form.append("whitelist", $("#link-card-whitelist").value);
  form.append("blacklist", $("#link-card-blacklist").value);
  try {
    const response = await fetch("/api/admin/link-card-config", { method: "POST", headers: adminHeaders(), body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    renderLinkCardConfig(data.link_card_config || {});
    showAdmin("<p>链接卡片规则已保存。</p>");
  } catch (error) {
    showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
  }
});

loadAdmin().catch((error) => {
  showAdmin(`<p class="text-red-600">${escapeHtml(error.message)}</p>`);
});
