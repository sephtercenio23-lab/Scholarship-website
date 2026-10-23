function applicationDetailsHtml(app, editable) {
  const discountEditable = editable && app.status === "Approved" && !app.archived;
  const gradeRemarks = [
    app.hasFailingGrade ? "Failing grade" : "",
    app.hasIncompleteGrade ? "INC" : "",
    app.hasDroppedGrade ? "Dropped" : "",
  ].filter(Boolean);
  const documentsHtml = [...SCHOLARSHIP_REQUIREMENTS, ...(app.documents.terminalReport ? [{ key: "terminalReport", label: "Terminal report" }] : [])].map((requirement) => {
    const doc = app.documents[requirement.key];
    if (doc && doc.name) {
      return `
        <button type="button" class="document-preview" data-file-app="${app.id}" data-file-key="${requirement.key}" title="Click to view this file">
          <i class="ti ti-file-text"></i>
          <span>${requirement.label}<small>${escapeHtml(doc.name)}${requirement.key === "terminalReport" ? " · " + formatDate(doc.uploadedAt) + " · " + (app.reportReceivedAt ? "Received" : "Submitted") : ""}</small></span>
          <i class="ti ti-eye view-icon"></i>
        </button>`;
    }
    return `
      <div class="document-preview document-missing">
        <i class="ti ti-file-off"></i>
        <span>${requirement.label}<small>Not submitted</small></span>
      </div>`;
  }).join("");
  const historyHtml = app.history
    .map(
      (entry) => `
    <li>
      <strong>${entry.status}</strong>
      <small>${formatDateTime(entry.date)}${entry.by ? " &middot; " + escapeHtml(entry.by) : ""}</small>
      ${entry.remarks ? `<p>${escapeHtml(entry.remarks)}</p>` : ""}
    </li>`
    )
    .join("");
  const termHtml = app.term
    ? `
    <div class="term-tag-row">
      <span class="term-tag ${app.archived ? "term-past" : ""}">
        <i class="ti ti-calendar-event"></i> ${escapeHtml(applicationTermLabel(app))}
      </span>
      ${app.archived ? '<span class="term-tag-note">Past term &middot; kept for records, no longer being evaluated</span>' : ""}
    </div>`
    : termTag(app);
  return `
    ${termHtml}
    <div class="detail-banner">
      <div>
        <span class="micro">${app.code}</span>
        <h3>${app.scholarshipType}</h3>
      </div>
      ${statusBadge(app.status)}
    </div>

    <dl class="detail-list">
      <dt>Student</dt><dd>${escapeHtml(app.studentName)} (${escapeHtml(app.studentId)})</dd>
      <dt>Email</dt><dd>${escapeHtml(app.universityEmail)}</dd>
      <dt>Program / year</dt><dd>${escapeHtml(app.program)} &middot; ${escapeHtml(app.yearLevel)}</dd>
      <dt>GWA</dt><dd>${app.gwa ? escapeHtml(app.gwa) : "\u2014"}</dd>
      <dt>Lowest grade</dt><dd>${app.lowestGrade ? escapeHtml(app.lowestGrade) : "\u2014"}</dd>
      <dt>Grade remarks</dt><dd>${gradeRemarks.length ? escapeHtml(gradeRemarks.join(", ")) : "No failing grade, INC, or dropped remarks declared"}</dd>
      <dt>Term</dt><dd>${escapeHtml(app.term || "\u2014")}</dd>
      <dt>Submitted</dt><dd>${formatDate(app.dateSubmitted)}</dd>
      <dt>Tuition fee discount</dt><dd data-discount-cell><span class="discount-value">${app.discountPercent ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span>${discountEditable ? ' <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>' : ""}</dd>
      ${app.status === "Approved" ? `<dt>Duty rendered</dt><dd data-duty-cell>${dutyDetailsHtml(app)}</dd>` : ""}
    </dl>

    <h3 class="modal-subhead">Submitted requirements</h3>
    <div class="submitted-documents">${documentsHtml}</div>
    ${app.documents.terminalReport ? `<p><span class="badge">${app.reportReceivedAt ? "Received" : "Submitted"}</span> ${formatDate(app.documents.terminalReport.uploadedAt)}</p>${currentUser.role !== "student" && !app.reportReceivedAt ? `<button class="btn btn-outline btn-sm" type="button" data-receive-report="${app.id}" ${app.archived ? 'disabled title="Past term, read-only"' : ""}>Mark as received</button>` : ""}` : ""}

    <h3 class="modal-subhead">Status history</h3>
    <ol class="status-history">${historyHtml}</ol>`;
}

function wireDocumentButtons(container) {
  container.querySelectorAll('[data-file-app]:not([data-file-key="terminalReport"])').forEach((button) => {
    button.addEventListener("click", () =>
      viewStoredDocument(button.dataset.fileApp, button.dataset.fileKey)
    );
  });
}

function wireDiscountEdit(container, app, onUpdated) {
  const cell = container.querySelector("[data-discount-cell]");
  if (!cell) return;
  function renderView() {
    cell.innerHTML = `<span class="discount-value">${app.discountPercent ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span> <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>`;
  }
  function renderEdit() {
    cell.innerHTML = `
      <input type="number" class="discount-edit-input" min="0" max="100" step="1" value="${escapeHtml(app.discountPercent)}" />
      <button type="button" class="icon-btn" data-discount-action="save" title="Save"><i class="ti ti-check"></i></button>
      <button type="button" class="icon-btn" data-discount-action="cancel" title="Cancel"><i class="ti ti-x"></i></button>`;
    cell.querySelector(".discount-edit-input").focus();
  }
  cell.addEventListener("click", (e) => {
    const action = e.target.closest("[data-discount-action]");
    if (!action) return;
    if (action.dataset.discountAction === "edit") {
      renderEdit();
    } else if (action.dataset.discountAction === "cancel") {
      renderView();
    } else if (action.dataset.discountAction === "save") {
      runPage(async () => {
        const value = cell.querySelector(".discount-edit-input").value.trim();
        const updated = await updateApplicationDiscount(app.id, value);
        app.discountPercent = updated.discountPercent;
        renderView();
        showToast("Tuition fee discount updated.");
        if (onUpdated) onUpdated(updated);
      });
    }
  });
}
function studentDutyHtml(app) {
  if (app.status !== "Approved") return "";
  const doc = app.documents?.terminalReport;
  const available = Number(app.dutyHours) === 80;
  return `<div>Duty rendered: ${dutyKey(app)}</div>
    ${doc ? `<div>Terminal report submitted on ${formatDate(doc.uploadedAt)} <button type="button" class="text-link" data-file-app="${app.id}" data-file-key="terminalReport">View</button> ${app.reportReceivedAt ? '<span class="badge">Received</span>' : ""}</div>` : ""}
    ${app.reportReceivedAt ? "" : available ? `<button type="button" class="btn btn-outline btn-sm" data-submit-report="${app.id}">${doc ? "Replace terminal report" : "Submit terminal report"}</button>` : '<span class="term-tag-note" aria-disabled="true">Available once your 80 hours are complete</span>'}`;
}

function dutyDetailsHtml(app) {
  if (currentUser.role === "student") return studentDutyHtml(app);
  return `${dutyKey(app)} <button type="button" class="icon-btn" data-duty-edit="${app.id}" ${app.archived ? 'disabled title="Past term, read-only"' : 'title="Edit duty rendered"'}><i class="ti ti-pencil"></i></button>`;
}

document.addEventListener("click", (event) => {
  const edit = event.target.closest("[data-duty-edit]");
  const submit = event.target.closest("[data-submit-report]");
  const receive = event.target.closest("[data-receive-report]");
  const file = event.target.closest('[data-file-key="terminalReport"]');
  if (file) {
    event.stopPropagation();
    runPage(() => viewStoredDocument(file.dataset.fileApp, "terminalReport"));
  }
  if (edit && !edit.disabled) runPage(async () => {
    const app = await getApplicationById(edit.dataset.dutyEdit);
    const cell = edit.closest("[data-duty-cell]");
    cell.innerHTML = `
      <select class="plain-select" id="dutyStatus" aria-label="Duty rendered status">${["Not Started", "In Progress", "Completed the 80 Hours"].map((option) => `<option ${dutyKey(app) === option ? "selected" : ""}>${option}</option>`).join("")}</select>
      <input type="number" class="discount-edit-input" id="dutyHours" aria-label="Hours rendered" min="1" max="79" value="${Math.max(1, Math.min(79, Number(app.dutyHours || 1)))}" ${dutyKey(app) !== "In Progress" ? "hidden" : ""} />
      <button type="button" class="icon-btn" id="saveDuty" title="Save"><i class="ti ti-check"></i></button>
      <button type="button" class="icon-btn" id="cancelDuty" title="Cancel"><i class="ti ti-x"></i></button>`;
    el("dutyStatus").addEventListener("change", () => { el("dutyHours").hidden = val("dutyStatus") !== "In Progress"; });
    el("cancelDuty").addEventListener("click", () => { cell.innerHTML = dutyDetailsHtml(app); });
    el("saveDuty").addEventListener("click", () => runPage(async () => {
      const status = val("dutyStatus");
      const hours = status === "In Progress" ? Number(val("dutyHours")) : status === "Not Started" ? 0 : 80;
      if (status === "In Progress" && (!Number.isInteger(hours) || hours < 1 || hours > 79)) throw new Error("Enter hours rendered from 1 to 79.");
      await updateDutyRendered(app.id, hours, status === "Completed the 80 Hours");
      setFlash("Duty rendered updated.");
      const url = new URL(window.location.href);
      url.searchParams.set("view", app.id);
      window.location.href = url.href;
    }));
  });
  if (submit) runPage(() => openReportModal(submit.dataset.submitReport));
  if (receive && !receive.disabled) runPage(async () => {
    await receiveTerminalReport(receive.dataset.receiveReport);
    setFlash("Terminal report marked as received.");
    const url = new URL(window.location.href);
    url.searchParams.set("view", receive.dataset.receiveReport);
    window.location.href = url.href;
  });
});

async function openReportModal(appId) {
  const app = await getApplicationById(appId);
  if (!app || app.status !== "Approved" || Number(app.dutyHours) !== 80 || app.reportReceivedAt) throw new Error("Terminal report is not available or has already been received.");
  if (!el("reportModal")) document.body.insertAdjacentHTML("beforeend", `
    <div class="modal-overlay" id="reportModal"><div class="modal">
      <div class="modal-heading"><h2>Submit terminal report</h2><button type="button" class="close" data-close-modal aria-label="Close dialog"><i class="ti ti-x"></i></button></div>
      <div id="reportModalBody"></div>
    </div></div>`);
  el("reportModalBody").innerHTML = `
    ${termTag(app)}
    <p class="modal-text">${escapeHtml(app.scholarshipType)} · ${escapeHtml(app.code)}</p>
    <form id="reportForm">
      <div class="form-group"><label for="reportFile">PDF, JPG or PNG, up to ${MAX_FILE_SIZE_MB} MB</label><input type="file" id="reportFile" accept=".pdf,.jpg,.jpeg,.png" required /></div>
      <div class="alert alert-error" id="reportAlert"></div>
      <div class="modal-actions"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button type="submit" class="btn btn-primary" id="reportSubmit">Submit</button></div>
    </form>`;
  el("reportForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runPage(async () => {
      hideAlert("reportAlert");
      const file = el("reportFile").files[0];
      const check = validateFile(file);
      if (!check.valid) {
        showAlert("reportAlert", check.message);
        return;
      }
      el("reportSubmit").disabled = true;
      let path = "";
      try {
        path = storagePathFor(currentUser.id, app.id, "terminalReport", file.name);
        await uploadStoredFile(path, file);
        await submitTerminalReport(app.id, { name: file.name, path, uploadedAt: new Date().toISOString(), sizeBytes: file.size, mimeType: fileMimeType(file) });
        setFlash("Terminal report submitted.");
        window.location.href = `my-applications.html?view=${app.id}`;
      } catch (error) {
        if (path) await discardStoredFiles([path]).catch(() => {});
        showAlert("reportAlert", friendlyError(error));
        el("reportSubmit").disabled = false;
      }
    });
  });
  openModal("reportModal");
}
