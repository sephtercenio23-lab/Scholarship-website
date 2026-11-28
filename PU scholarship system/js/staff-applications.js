let currentUser = null;
let allApps = [];
let activeTab = "All";
let openAppId = null;
let pendingDeleteId = null;
let pendingDecision = null;

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["staff", "president", "executive_president", "super_admin"]);
  if (!currentUser) return;
  initSidebar(currentUser, "applications");
  const canExport = ["staff", "president", "executive_president", "admin", "super_admin"].includes(
    currentUser.role
  );
  el("exportExcelBtn").hidden = !canExport;
  el("typeFilter").innerHTML += SCHOLARSHIP_TYPES.map((type) => `<option value="${type}">${type}</option>`).join("");
  const requestedStatus = getQueryParam("status");
  const requestedTab = el("statusTabs").querySelector(`[data-status="${requestedStatus}"]`);
  if (requestedTab) {
    el("statusTabs").querySelectorAll(".tab-btn").forEach((t) => t.classList.remove("active"));
    requestedTab.classList.add("active");
    activeTab = requestedTab.dataset.status;
  }
  initExtraFilters();
  await Promise.all([
    reloadData(),
    initViewing(document.querySelector(".table-toolbar"), true, async () => { showApplications(); }),
  ]);
  const currentTerm = viewingTerms.find((term) => term.state === "Current") || (await getCurrentTerm());
  el("termText").textContent = currentTerm.label;
  showApplications();
  const requested = getQueryParam("view");
  if (requested) openReview(requested);
  window.addEventListener("notification-arrived", () =>
    runPage(async () => {
      await reloadData();
      showApplications();
    })
  );
  el("statusTabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab-btn");
    if (!tab) return;
    el("statusTabs").querySelectorAll(".tab-btn").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    activeTab = tab.dataset.status;
    const url = new URL(window.location.href);
    url.searchParams.set("status", activeTab);
    history.replaceState(null, "", url);
    runPage(showApplications);
  });
  el("searchBox").addEventListener("input", showApplications);
  el("typeFilter").addEventListener("change", showApplications);
  el("clearFiltersBtn").addEventListener("click", () => {
    el("searchBox").value = "";
    el("typeFilter").value = "";
    document.querySelector(".table-toolbar").resetViewing();
    el("programFilter").value = "";
    showApplications();
  });
  el("selectEligible").addEventListener("change", (event) => {
    bulkBoxes().forEach(box => { box.checked = event.target.checked; });
    syncBulkSelection();
  });
  el("applicationRows").addEventListener("change", syncBulkSelection);
  el("bulkApprove").addEventListener("click", () => runPage(approveSelected));
  el("exportExcelBtn").addEventListener("click", () => runPage(exportExcel));
  el("applicationRows").addEventListener("click", (e) => {
    const button = e.target.closest("[data-open-app]");
    if (button) openReview(button.dataset.openApp);
    const deleteButton = e.target.closest("[data-delete-app]");
    if (deleteButton) askToDelete(deleteButton.dataset.deleteApp);
  });
  el("deleteConfirmBtn").addEventListener("click", () => runPage(confirmDelete));
  el("evalArea").addEventListener("click", (e) => {
    const button = e.target.closest("[data-action]");
    if (!button) return;
    if (button.dataset.action === "start") runPage(() => startEvaluation(button));
    if (button.dataset.action === "Approved" || button.dataset.action === "Rejected") {
      askToConfirm(button.dataset.action);
    }
    if (button.dataset.action === "reopen") askToReopen();
  });
  el("evalArea").addEventListener("click", (e) => {
    const accept = e.target.closest("[data-appeal-accept]");
    const decline = e.target.closest("[data-appeal-decline]");
    const cancel = e.target.closest("[data-appeal-cancel]");
    const confirm = e.target.closest("[data-appeal-confirm]");
    if (accept) runPage(() => respondToAppeal(accept.dataset.appealAccept, "Accepted", "", accept));
    if (decline) showAppealDeclineForm(decline.dataset.appealDecline);
    if (cancel) {
      const app = allApps.find((item) => item.id === openAppId);
      if (app) showEvaluation(app);
    }
    if (confirm) {
      runPage(async () => {
        const response = val("appealResponse");
        if (!response) {
          showAlert("staffAppealAlert", "Please provide a response before declining this appeal.");
          return;
        }
        await respondToAppeal(confirm.dataset.appealConfirm, "Declined", response, confirm);
      });
    }
  });
  el("confirmActionBtn").addEventListener("click", () => runPage(applyDecision));
}

function rowActionsHtml(appId) {
  return `
    <div class="row-actions">
      <button type="button" class="btn btn-outline btn-sm" data-open-app="${appId}"><i class="ti ti-eye"></i> View</button>
      <button type="button" class="btn btn-danger btn-sm" data-delete-app="${appId}" ${allApps.find((app) => app.id === appId)?.archived ? 'disabled title="Past term, read-only"' : ""}><i class="ti ti-trash"></i> Delete</button>
    </div>`;
}

async function reloadData() {
  allApps = await getAllApplications();
}

// Tabs group the status flow: "Under Evaluation" covers every level before the final
// decision and "Approved" covers every fully approved status (legacy rows included).
function tabMatches(app) {
  if (activeTab === "All") return true;
  if (activeTab === CHANGED_AFTER_FINANCE) return isChangedAfterFinance(app);
  if (activeTab === "Under Evaluation") return isPendingApprovalStatus(app.status);
  if (activeTab === "Approved") return isApprovedStatus(app.status);
  if (activeTab === "Pending Appeal") return app.status === "Rejected" && app.appeal && app.appeal.status === "Pending";
  return app.status === activeTab;
}

function isFinanceSent(app) {
  return Boolean(
    (app && app.financeSentAt) || (app && ["Sent to Finance", "Exported"].includes(app.status)) || isChangedAfterFinance(app)
  );
}

function currentExportParams() {
  return {
    termId: viewingTerm || "",
    academicYear: !viewingTerm && viewingYear ? viewingYear : "",
    scholarshipType: el("typeFilter").value,
    status: "Approved",
    search: el("searchBox").value.trim(),
    program: val("programFilter"),
  };
}

async function downloadApplicationsExport(fetcher, label, fallbackName) {
  const response = await fetcher(currentExportParams());
  if (response.status === 204) {
    showToast("No applications match your filters.");
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = exportFilename(response, fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast(`${label} file downloaded.`);
  // Exports are read-only records of the approved scholars; refresh the table and preview.
  await reloadData();
  showApplications();
  if (openAppId) openReview(openAppId);
}

async function exportExcel() {
  const button = el("exportExcelBtn");
  setButtonBusy(button, "Exporting...");
  try {
    await downloadApplicationsExport(exportApplicationsExcel, "Excel", "applications.xlsx");
  } finally {
    clearButtonBusy(button);
  }
}

function exportFilename(response, fallbackName) {
  const match = (response.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/);
  return match ? match[1] : fallbackName;
}

function scopedApplications() {
  return allApps.filter(
    (app) => matchesViewing(app) && !(selectedViewingTerm()?.trimester === "3rd Trimester" && /nursing/i.test(app.program))
  );
}

function bulkEligible(app) {
  return !app.archived && ["president", "executive_president"].includes(currentUser?.role)
    && isPendingApprovalStatus(app.status) && canApproveStage(currentUser.role, nextApprovalStage(app)?.key);
}

const bulkBoxes = () => [...document.querySelectorAll("#applicationRows [data-bulk-id]")];
let bulkBusy = false;
function syncBulkSelection() {
  const boxes = bulkBoxes();
  const count = boxes.filter(box => box.checked).length;
  el("bulkControls").hidden = !boxes.length;
  el("selectEligible").checked = count > 0 && count === boxes.length;
  el("selectEligible").indeterminate = count > 0 && count < boxes.length;
  el("bulkApprove").disabled = bulkBusy || !count;
}

async function approveSelected() {
  const ids = bulkBoxes().filter(box => box.checked).map(box => box.dataset.bulkId);
  const final = currentUser.role === "executive_president";
  if (bulkBusy || !ids.length || !window.confirm(`Approve ${ids.length} selected application(s)? ${final ? "This gives final approval and triggers Finance processing. Existing discounts are unchanged." : "They will be forwarded to the University President."}`)) return;
  bulkBusy = true;
  syncBulkSelection();
  let approved = 0;
  const failures = [];
  try {
    for (const id of ids) {
      try {
        const updated = await updateApplicationStatus(id, "Approved", "");
        allApps = allApps.map(app => app.id === updated.id ? updated : app);
        approved++;
      } catch (error) {
        failures.push(`${allApps.find(app => app.id === id)?.code || id}: ${friendlyError(error)}`);
      }
    }
    if (failures.length) window.alert(`Approved ${approved} of ${ids.length}. Not confirmed:\n${failures.join("\n")}`);
    else showToast(`Approved ${approved} application(s).`);
  } finally {
    bulkBusy = false;
    showApplications();
  }
}

function showApplications() {
  if (!el("programFilter") || !el("viewingTerm")) return;
  const scoped = scopedApplications();
  refreshFilterOptions(scoped);
  const search = el("searchBox").value.trim().toLowerCase();
  const type = el("typeFilter").value;
  // The approved-only columns (and their search fields) show on every fully approved tab.
  const showingApproved = isApprovedStatus(activeTab);
  const applications = sortApplications(scoped).filter((app) => {
    if (val("programFilter") && app.program !== val("programFilter")) return false;
    if (!tabMatches(app)) return false;
    if (type && app.scholarshipType !== type) return false;
    if (search) {
      const fields = [
        app.code,
        app.program,
        app.term,
        app.academicYear,
        app.trimester,
        app.studentName,
        app.studentId,
        app.scholarshipType,
        formatDate(app.dateSubmitted),
        app.discountPercent !== null && app.discountPercent !== undefined ? app.discountPercent + "%" : "",
        pastDiscountLabel(app.pastDiscount),
        statusLabel(app.status),
      ];
      if (showingApproved) {
        fields.push(app.program, app.yearLevel, formatDate(app.approvedAt), app.approvedBy);
      }
      if (!fields.join(" ").toLowerCase().includes(search)) return false;
    }
    return true;
  });
  document.querySelectorAll(".approved-only").forEach((th) => {
    th.hidden = !showingApproved;
  });
  el("applicationRows").innerHTML = applications
    .map((app) => {
      const approvedCells = showingApproved
        ? `
      <td data-label="Program / year">${escapeHtml(app.program)} &middot; ${escapeHtml(app.yearLevel)}</td>
      <td data-label="Approved on">${app.approvedAt ? formatDate(app.approvedAt) : "&mdash;"}</td>
      <td data-label="Approved by">${app.approvedAt ? escapeHtml(app.approvedBy) : "&mdash;"}</td>`
        : "";
      return `
    <tr>
      <td data-label="Application ID">${bulkEligible(app) ? `<input type="checkbox" data-bulk-id="${escapeHtml(app.id)}" aria-label="Select ${escapeHtml(app.code)}" /> ` : ""}${app.code}</td>
      <td data-label="Term">${termTag(app)}</td>
      <td data-label="Student"><div><strong>${escapeHtml(app.studentName)}</strong><small>${escapeHtml(app.studentId)}</small></div></td>
      <td data-label="Scholarship">${app.scholarshipType}</td>
      <td data-label="Submitted">${formatDate(app.dateSubmitted)}</td>${approvedCells}
      <td data-label="Discount %">${app.discountPercent !== null && app.discountPercent !== undefined ? escapeHtml(app.discountPercent) + "%" : "&mdash;"}<small>Past: ${pastDiscountLabel(app.pastDiscount)}</small></td>
      <td data-label="Status">${applicationStatusBadges(app)}</td>
      <td data-label="">${rowActionsHtml(app.id)}</td>
    </tr>`;
    })
    .join("");
  if (el("bulkControls")) syncBulkSelection();
  el("filterCount").textContent = `Showing ${applications.length} of ${scoped.length} application${scoped.length === 1 ? "" : "s"}`;
  el("emptyState").classList.toggle("hidden", applications.length > 0);
}

function openReview(appId) {
  const app = allApps.find((item) => item.id === appId);
  if (!app) return;
  openAppId = appId;
  hideAlert("evalAlert");
  el("reviewBody").innerHTML = applicationDetailsHtml(app, true);
  wireDiscountEdit(el("reviewBody"), app, (updated) => {
    allApps = allApps.map((item) => (item.id === updated.id ? updated : item));
    showApplications();
  });
  showEvaluation(app);
  openModal("reviewModal");
}

function showEvaluation(app) {
  if (app.archived) {
    el("evalArea").innerHTML = '<button type="button" class="btn btn-outline" disabled title="Past term, read-only">Past term, read-only</button>';
    return;
  }
  if (app.status === "Submitted") {
    const canStart = approvalStageForRole(currentUser.role) !== null;
    el("evalArea").innerHTML = canStart
      ? `
      <p class="modal-text">Review the documents above. You can start the evaluation before or after the application deadline. The student will be notified.</p>
      <button type="button" class="btn btn-primary" data-action="start"><i class="ti ti-hourglass"></i> Start evaluation</button>`
      : `<p class="modal-text">Waiting for an authorized reviewer to start the evaluation.</p>`;
    return;
  }
  if (isPendingApprovalStatus(app.status)) {
    // Three-level approval: only the current stage approver sees the approve/reject actions.
    const stage = nextApprovalStage(app);
    if (!stage || !canApproveStage(currentUser.role, stage.key)) {
      el("evalArea").innerHTML = `<p class="modal-text">Waiting for ${stage ? stage.label : "the next approver"} approval.</p>`;
      return;
    }
    const isFinal = stage.key === "executivePresident";
    el("evalArea").innerHTML = `
      <p class="modal-text">You are acting as ${stage.label}${stage.office ? " · " + stage.office : ""}.${isFinal ? ` This is the final approval: the scholar is emailed to Finance in Excel format and the student then sees Approved.${isChangedAfterFinance(app) ? " This is a correction, so the correction list is sent to Finance instead." : ""}` : " The student will see Approved only after all three approvals."}</p>
      <div class="form-group" ${isFinal ? "" : "hidden"}>
        <label for="evalDiscount">Tuition fee discount percent (optional)</label>
        <div class="input-wrap"><i class="ti ti-discount-2"></i><input type="number" id="evalDiscount" min="0" max="100" step="1" placeholder="e.g. 100" /></div>
      </div>
      <div class="form-group">
        <label for="evalRemarks">Remarks (required to reject, optional to approve)</label>
        <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="evalRemarks" placeholder="Add evaluation remarks..."></textarea></div>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn btn-primary" data-action="Approved"><i class="ti ti-circle-check"></i> ${stage.verb}</button>
        <button type="button" class="btn btn-danger" data-action="Rejected"><i class="ti ti-circle-x"></i> Reject</button>
      </div>`;
    return;
  }
  const reopenHtml =
    ["staff", "admin", "super_admin"].includes(currentUser.role) && !app.archived
      ? `
    <div class="form-group">
      <label for="reopenReason">Reopen this application</label>
      <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="reopenReason" placeholder="Reason for reopening, e.g. approved by mistake..."></textarea></div>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-outline" data-action="reopen"><i class="ti ti-rotate-2"></i> Reopen for evaluation</button>
    </div>`
      : "";
  el("evalArea").innerHTML = `
    <div class="alert ${isApprovedStatus(app.status) ? "alert-success" : "alert-error"} show">
      <strong>${escapeHtml(statusLabel(app.status))}</strong>${app.remarks ? ", " + escapeHtml(app.remarks) : ""}
      ${app.evaluatedBy ? `<br><span class="you-note">Evaluated by ${escapeHtml(app.evaluatedBy)}</span>` : ""}
    </div>${reopenHtml}${staffAppealHtml(app)}`;
}

function staffAppealHtml(app) {
  const appeal = app.appeal;
  if (!appeal || app.status !== "Rejected" || app.archived || appeal.status !== "Pending") return "";
  return `
  <h3 class="modal-subhead">Appeal decision</h3>
  <div id="appealResponseArea">
    <p class="modal-text">The student appealed this rejection. Accepting moves the application back to Under Evaluation and notifies the student.</p>
    <div class="inline-actions">
      <button type="button" class="btn btn-primary btn-sm" data-appeal-accept="${app.id}"><i class="ti ti-circle-check"></i> Accept appeal</button>
      <button type="button" class="btn btn-danger btn-sm" data-appeal-decline="${app.id}"><i class="ti ti-circle-x"></i> Decline appeal</button>
    </div>
  </div>
  <div class="alert alert-error" id="staffAppealAlert"></div>`;
}

function showAppealDeclineForm(appId) {
  hideAlert("staffAppealAlert");
  el("appealResponseArea").innerHTML = `
    <div class="form-group">
      <label for="appealResponse">Response (required, shown to the student)</label>
      <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="appealResponse" maxlength="1000" placeholder="Explain why the appeal is declined..."></textarea></div>
    </div>
    <div class="inline-actions">
      <button type="button" class="btn btn-outline btn-sm" data-appeal-cancel>Cancel</button>
      <button type="button" class="btn btn-danger btn-sm" data-appeal-confirm="${appId}"><i class="ti ti-circle-x"></i> Confirm decline</button>
    </div>`;
}

async function respondToAppeal(appId, decision, response, button) {
  setButtonBusy(button, decision === "Accepted" ? "Accepting..." : "Declining...");
  try {
    await respondApplicationAppeal(appId, decision, response);
  } catch (error) {
    clearButtonBusy(button);
    showAlert("staffAppealAlert", friendlyError(error));
    return;
  }
  setFlash(
    decision === "Accepted"
      ? "Appeal accepted; the application is under evaluation again."
      : "Appeal declined; the student was notified."
  );
  const url = new URL(window.location.href);
  url.searchParams.set("view", appId);
  window.location.href = url.href;
}

async function saveStatus(status, remarks, discountPercent) {
  try {
    const updated = await updateApplicationStatus(openAppId, status, remarks, discountPercent);
    allApps = allApps.map((app) => (app.id === updated.id ? updated : app));
    return true;
  } catch (error) {
    closeModal("confirmModal");
    showAlert("evalAlert", friendlyError(error));
    return false;
  }
}

async function startEvaluation(button) {
  setButtonBusy(button, "Starting...");
  if (!(await saveStatus("Under Evaluation", ""))) {
    clearButtonBusy(button);
    return;
  }
  showToast("Application moved to Under Evaluation.");
  refreshAfterChange();
}

function askToConfirm(decision) {
  const app = allApps.find((item) => item.id === openAppId);
  const remarks = el("evalRemarks").value.trim();
  const discountPercent = el("evalDiscount").value.trim();
  hideAlert("evalAlert");
  const approving = decision === "Approved";
  if (approving && discountPercent !== "" && (!/^\d+$/.test(discountPercent) || Number(discountPercent) < 0 || Number(discountPercent) > 100)) {
    showAlert("evalAlert", "Discount percent must be a whole number from 0 to 100.");
    return;
  }
  if (decision === "Rejected" && !remarks) {
    showAlert("evalAlert", "Please provide a reason or remarks before rejecting this application.");
    return;
  }
  const stage = nextApprovalStage(app);
  pendingDecision = { decision, remarks, discountPercent };
  el("confirmTitle").textContent = approving ? `Confirm ${stage ? stage.verb.toLowerCase() : "approval"}` : "Confirm rejection";
  el("confirmText").textContent = approving
    ? stage && stage.key === "executivePresident"
      ? `Are you sure you want to give final approval to ${app.code} (${app.studentName}) as ${stage.label}? ${isChangedAfterFinance(app) ? "The correction list" : "The approved scholar"} will be emailed to Finance in Excel format and the student will then see Approved.`
      : `Are you sure you want to ${stage ? stage.verb.toLowerCase() : "approve"} ${app.code} (${app.studentName}) as ${stage ? stage.label : "approver"}? It will be forwarded to the next approver and the student will not see Approved yet.`
    : `Are you sure you want to reject ${app.code} (${app.studentName}) as ${stage ? stage.label : "approver"}? The student will see your remarks.`;
  el("confirmActionBtn").className = "btn " + (approving ? "btn-primary" : "btn-danger");
  el("confirmActionBtn").textContent = approving ? `Yes, ${stage ? stage.verb.toLowerCase() : "approve"}` : "Yes, reject";
  openModal("confirmModal");
}

function askToReopen() {
  const app = allApps.find((item) => item.id === openAppId);
  const reason = el("reopenReason").value.trim();
  hideAlert("evalAlert");
  if (!reason) {
    showAlert("evalAlert", "Please provide a reason for reopening this application.");
    return;
  }
  pendingDecision = { reopen: true, remarks: reason };
  el("confirmTitle").textContent = "Confirm reopen";
  el("confirmText").textContent = isFinanceSent(app)
    ? `Reopen ${app.code} (${app.studentName})? Finance already received this scholar, so it will be flagged "${CHANGED_AFTER_FINANCE}" and must be approved again by ${ROLE_LABELS.staff}, the ${ROLE_LABELS.president}, and the ${ROLE_LABELS.executive_president}. The correction list is emailed to Finance after the last approval, and the student is notified.`
    : `Reopen ${app.code} (${app.studentName})? It will go back to Under Evaluation, the current decision (${statusLabel(app.status)}) and discount will be cleared, and the student will be notified.`;
  el("confirmActionBtn").className = "btn btn-primary";
  el("confirmActionBtn").textContent = "Yes, reopen";
  openModal("confirmModal");
}

async function applyReopen(button) {
  setButtonBusy(button, "Reopening...");
  let updated = null;
  try {
    updated = await reopenApplication(openAppId, pendingDecision.remarks);
    allApps = allApps.map((app) => (app.id === updated.id ? updated : app));
  } catch (error) {
    clearButtonBusy(button);
    closeModal("confirmModal");
    showAlert("evalAlert", friendlyError(error));
    return;
  }
  clearButtonBusy(button);
  closeModal("confirmModal");
  showToast(
    updated && isChangedAfterFinance(updated)
      ? `Application reopened and flagged "${CHANGED_AFTER_FINANCE}". It needs the three approvals again.`
      : "Application reopened and moved to Under Evaluation."
  );
  refreshAfterChange();
}

async function applyDecision() {
  const button = el("confirmActionBtn");
  if (pendingDecision.reopen) return applyReopen(button);
  const { decision, remarks, discountPercent } = pendingDecision;
  setButtonBusy(button, decision === "Approved" ? "Approving..." : "Rejecting...");
  if (!(await saveStatus(decision, remarks, discountPercent))) {
    clearButtonBusy(button);
    return;
  }
  clearButtonBusy(button);
  closeModal("confirmModal");
  const updated = allApps.find((item) => item.id === openAppId);
  const sentToFinance = updated && updated.status === "Sent to Finance";
  showToast(
    decision === "Rejected"
      ? "Application rejected."
      : sentToFinance
        ? "Approved scholar sent to Finance in Excel format."
        : updated && isApprovedStatus(updated.status)
          ? "Application approved."
          : "Approval recorded; waiting for the next approver."
  );
  refreshAfterChange();
}

function askToDelete(appId) {
  const app = allApps.find((item) => item.id === appId);
  if (!app) return;
  pendingDeleteId = appId;
  el("deleteText").textContent = `Are you sure you want to delete ${app.code} (${app.studentName})? This removes the application and its documents and cannot be undone.`;
  openModal("deleteModal");
}

async function confirmDelete() {
  const button = el("deleteConfirmBtn");
  hideAlert("deleteAlert");
  setButtonBusy(button, "Deleting...");
  let removed = null;
  try {
    removed = await deleteApplication(pendingDeleteId);
  } catch (error) {
    clearButtonBusy(button);
    showAlert("deleteAlert", friendlyError(error));
    return;
  }
  clearButtonBusy(button);
  allApps = allApps.filter((app) => app.id !== removed.id);
  pendingDeleteId = null;
  closeModal("deleteModal");
  showApplications();
  showToast(`Application ${removed.code} deleted.`);
  await deleteApplicationFiles(removed).catch((error) => {
    console.error(error);
    showToast("The application was deleted, but some uploaded files could not be removed.", true);
  });
}

function refreshAfterChange() {
  openReview(openAppId);
  showApplications();
}
function initExtraFilters() {
  const controls = [
    ["programFilter", "Program", []],
  ];
  controls.forEach(([id, label, options]) => {
    const optionsHtml = options
      .map((option) => {
        const value = typeof option === "string" ? option : option.value;
        const text = typeof option === "string" ? option : option.label;
        return `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`;
      })
      .join("");
    el("clearFiltersBtn").insertAdjacentHTML("beforebegin", `<select class="plain-select" id="${id}" aria-label="${label}"><option value="">${label}: All</option>${optionsHtml}</select>`);
    el(id).addEventListener("change", showApplications);
  });
}

function refreshFilterOptions(scoped = scopedApplications()) {
  const programs = [...new Set(scoped.map((app) => app.program).filter(Boolean))].sort();
  [
    ["programFilter", "Program", programs],
  ].forEach(([id, label, options]) => {
    const html = `<option value="">${label}: All</option>${options.map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join("")}`;
    if (el(id).dataset.options === html) return;
    const selected = el(id).value;
    el(id).innerHTML = html;
    el(id).dataset.options = html;
    el(id).value = options.includes(selected) ? selected : "";
  });
}
