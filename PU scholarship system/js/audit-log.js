let currentUser = null;
let auditPage = 1;
let totalEntries = 0;
const pageSize = 20;
const filters = { action: "", actor: "", fromDate: "", toDate: "" };

const AUDIT_ACTIONS = [
  { value: "account_created", label: "Account created" },
  { value: "account_updated", label: "Account updated" },
  { value: "account_deleted", label: "Account deleted" },
  { value: "term_changed", label: "Current term changed" },
  { value: "scholarships_updated", label: "Term scholarships updated" },
  { value: "application_deleted", label: "Application deleted" },
  { value: "application_reopened", label: "Application reopened" },
  { value: "password_changed", label: "Password changed" },
  { value: "account_locked", label: "Account locked" },
];

const ACTION_BADGE_CLASS = {
  account_created: "badge-approved",
  account_updated: "badge-submitted",
  account_deleted: "badge-rejected",
  term_changed: "badge-under-evaluation",
  scholarships_updated: "badge-submitted",
  application_deleted: "badge-rejected",
  application_reopened: "badge-under-evaluation",
  password_changed: "badge-submitted",
  account_locked: "badge-rejected",
};

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["admin"]);
  if (!currentUser) return;
  initSidebar(currentUser, "audit");
  el("actionFilter").innerHTML =
    '<option value="">All actions</option>' +
    AUDIT_ACTIONS.map((item) => `<option value="${item.value}">${item.label}</option>`).join("");
  el("actionFilter").addEventListener("change", () => {
    filters.action = el("actionFilter").value;
    auditPage = 1;
    runPage(loadAuditLog);
  });
  let actorTimer = null;
  el("actorFilter").addEventListener("input", () => {
    clearTimeout(actorTimer);
    actorTimer = setTimeout(() => {
      filters.actor = el("actorFilter").value.trim();
      auditPage = 1;
      runPage(loadAuditLog);
    }, 300);
  });
  el("fromDateFilter").addEventListener("change", () => {
    filters.fromDate = el("fromDateFilter").value;
    auditPage = 1;
    runPage(loadAuditLog);
  });
  el("toDateFilter").addEventListener("change", () => {
    filters.toDate = el("toDateFilter").value;
    auditPage = 1;
    runPage(loadAuditLog);
  });
  el("clearFiltersBtn").addEventListener("click", () => {
    filters.action = "";
    filters.actor = "";
    filters.fromDate = "";
    filters.toDate = "";
    el("actionFilter").value = "";
    el("actorFilter").value = "";
    el("fromDateFilter").value = "";
    el("toDateFilter").value = "";
    auditPage = 1;
    runPage(loadAuditLog);
  });
  el("prevPage").addEventListener("click", () => {
    if (auditPage <= 1) return;
    auditPage -= 1;
    runPage(loadAuditLog);
  });
  el("nextPage").addEventListener("click", () => {
    if (auditPage * pageSize >= totalEntries) return;
    auditPage += 1;
    runPage(loadAuditLog);
  });
  await loadAuditLog();
}

async function loadAuditLog() {
  const result = await getAuditLog({ ...filters, page: auditPage, pageSize });
  totalEntries = result.total;
  renderAuditLog(result.items);
}

function actionLabel(value) {
  const match = AUDIT_ACTIONS.find((item) => item.value === value);
  return match ? match.label : value;
}

function roleBadge(role) {
  if (!role) return '<span class="muted-text">\u2014</span>';
  const label = role === "staff" ? "Authorized staff" : role;
  return `<span class="badge badge-role-${role}">${label}</span>`;
}

function formatDetailValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return String(value);
  if (Object.prototype.hasOwnProperty.call(value, "from") && Object.prototype.hasOwnProperty.call(value, "to")) {
    return `${value.from} \u2192 ${value.to}`;
  }
  return Object.entries(value)
    .map(([key, inner]) => `${key}: ${formatDetailValue(inner)}`)
    .join(", ");
}

function detailsHtml(details) {
  const entries = Object.entries(details || {});
  if (!entries.length) return '<span class="muted-text">\u2014</span>';
  return entries
    .map(
      ([key, value]) =>
        `<div class="detail-line"><span class="detail-key">${escapeHtml(key)}</span> ${escapeHtml(
          formatDetailValue(value)
        )}</div>`
    )
    .join("");
}

function renderAuditLog(items) {
  el("auditRows").innerHTML = items
    .map(
      (entry) => `
    <tr>
      <td data-label="Date / time">${formatDateTime(entry.createdAt)}</td>
      <td data-label="Actor">${escapeHtml(entry.actorName || "\u2014")}</td>
      <td data-label="Role">${roleBadge(entry.actorRole)}</td>
      <td data-label="Action"><span class="badge ${ACTION_BADGE_CLASS[entry.action] || "badge-submitted"}">${escapeHtml(actionLabel(entry.action))}</span></td>
      <td data-label="Target"><span class="target-pill">${escapeHtml(entry.targetType)}</span>${
        entry.targetId ? `<div class="target-id">${escapeHtml(entry.targetId)}</div>` : ""
      }</td>
      <td data-label="Details">${detailsHtml(entry.details)}</td>
    </tr>`
    )
    .join("");
  el("emptyState").classList.toggle("hidden", items.length > 0);
  const totalPages = Math.max(1, Math.ceil(totalEntries / pageSize));
  el("pageInfo").textContent = totalEntries
    ? `Page ${auditPage} of ${totalPages} \u00b7 ${totalEntries} entries`
    : "No entries";
  el("prevPage").disabled = auditPage <= 1;
  el("nextPage").disabled = auditPage * pageSize >= totalEntries;
  const start = totalEntries === 0 ? 0 : (auditPage - 1) * pageSize + 1;
  const end = Math.min(auditPage * pageSize, totalEntries);
  el("filterCount").textContent = totalEntries
    ? `Showing ${start}\u2013${end} of ${totalEntries} entries`
    : "No entries found";
}
