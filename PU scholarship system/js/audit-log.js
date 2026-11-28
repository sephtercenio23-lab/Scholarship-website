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
  { value: "application_approved", label: "Approval recorded" },
  { value: "application_rejected", label: "Application rejected" },
  { value: "application_changed_after_finance", label: "Changed after sent to Finance" },
  { value: "applications_exported", label: "Applications exported" },
  { value: "scholars_sent_to_finance", label: "Scholars sent to Finance" },
  { value: "finance_correction_sent", label: "Correction list sent to Finance" },
  { value: "appeal_accepted", label: "Appeal accepted" },
  { value: "appeal_declined", label: "Appeal declined" },
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
  application_approved: "badge-approved",
  application_rejected: "badge-rejected",
  application_changed_after_finance: "badge-changed-after-finance",
  applications_exported: "badge-submitted",
  scholars_sent_to_finance: "badge-sent-to-finance",
  finance_correction_sent: "badge-sent-to-finance",
  appeal_accepted: "badge-approved",
  appeal_declined: "badge-rejected",
  password_changed: "badge-submitted",
  account_locked: "badge-rejected",
};

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["admin", "super_admin"]);
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
  el("dateFilter").addEventListener("change", () => {
    filters.fromDate = el("dateFilter").value;
    filters.toDate = el("dateFilter").value;
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
    el("dateFilter").value = "";
    auditPage = 1;
    runPage(loadAuditLog);
  });
  el("prevPage").addEventListener("click", () => {
    if (auditPage <= 1) return;
    auditPage -= 1;
    runPage(() => loadAuditLog(el("prevPage")));
  });
  el("nextPage").addEventListener("click", () => {
    if (auditPage * pageSize >= totalEntries) return;
    auditPage += 1;
    runPage(() => loadAuditLog(el("nextPage")));
  });
  await loadAuditLog();
}

async function loadAuditLog(busyButton) {
  if (busyButton) setButtonBusy(busyButton, "");
  let result = null;
  try {
    result = await getAuditLog({ ...filters, page: auditPage, pageSize });
  } finally {
    if (busyButton) clearButtonBusy(busyButton);
  }
  totalEntries = result.total;
  renderAuditLog(result.items);
}

function actionLabel(value) {
  const match = AUDIT_ACTIONS.find((item) => item.value === value);
  return match ? match.label : value;
}

function roleBadge(role) {
  if (!role) return '<span class="muted-text">\u2014</span>';
  const badgeClass = role === "student" ? "badge-role-student" : role === "staff" ? "badge-role-staff" : "badge-role-admin";
  return `<span class="badge ${badgeClass}">${escapeHtml(roleLabel(role))}</span>`;
}

const DETAIL_LABELS = {
  applications_exported: {
    count: "Applications exported",
    format: "File format",
    search: "Search text",
    codes: "Application codes",
  },
  application_approved: { stage: "Approval level", position: "Position", remarks: "Remarks" },
  application_rejected: { stage: "Approval level", position: "Position", remarks: "Remarks" },
  application_changed_after_finance: { flag: "Flag", reason: "Reason" },
  scholars_sent_to_finance: {
    recipient: "Recipient",
    attachment: "Attachment",
    approvers: "Approvers",
    emailQueued: "Email queued",
  },
  finance_correction_sent: {
    recipient: "Recipient",
    attachment: "Attachment",
    approvers: "Approvers",
    emailQueued: "Email queued",
  },
  term_changed: { from: "Previous term", to: "New term" },
  account_locked: { lockedMinutes: "Lock duration (minutes)", failedAttempts: "Failed sign-in attempts" },
};

// Translate stored field names for display without changing the audit record.
function detailLabel(key, action) {
  const label = DETAIL_LABELS[action]?.[key];
  if (typeof label === "string") return label;
  const words = key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1).replace(/\bid\b/g, "ID");
}

function formatDetailValue(value, field) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((item) => formatDetailValue(item, field)).join(", ");
  if (typeof value !== "object") {
    if (field === "stage" || field === "role") return roleLabel(value);
    if (field === "status") return statusLabel(value);
    return String(value);
  }
  if (Object.prototype.hasOwnProperty.call(value, "from") && Object.prototype.hasOwnProperty.call(value, "to")) {
    return `${formatDetailValue(value.from, field)} \u2192 ${formatDetailValue(value.to, field)}`;
  }
  return Object.entries(value)
    .map(([key, inner]) => `${detailLabel(key)}: ${formatDetailValue(inner, key) || "\u2014"}`)
    .join(", ");
}

function detailsHtml(details, action) {
  const entries = Object.entries(details || {});
  if (!entries.length) return '<span class="muted-text">\u2014</span>';
  return `<div class="audit-details">${entries
    .map(([key, value]) => {
      // Older approval records contain the position title in use when they were written.
      const text = key === "position" && details.stage ? roleLabel(details.stage) : formatDetailValue(value, key);
      return `<div class="detail-line"><span class="detail-key">${escapeHtml(detailLabel(key, action))}:</span> <span class="detail-value">${escapeHtml(text || "\u2014")}</span></div>`;
    })
    .join("")}</div>`;
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
      <td data-label="Target"><div class="audit-target"><span class="target-pill">${escapeHtml(entry.targetType)}</span>${
        entry.targetId ? `<div class="target-id">ID: ${escapeHtml(entry.targetId)}</div>` : ""
      }</div></td>
      <td data-label="Details">${detailsHtml(entry.details, entry.action)}</td>
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
