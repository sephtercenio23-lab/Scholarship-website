let currentUser = null;
let selectedScholarship = null;
let termScholarships = [];
let applicationTerm = null;
let currentTermApplications = [];
let chosenFiles = {};
let chosenFileObjects = {};

const GRADE_INPUT_PATTERN = /^\d+(\.\d{1,2})?$/;
const APPLY_GRADE_ERROR_IDS = ["applyGwaError", "applyLowestError", "applyRemarksError"];

runPage(startPage);

function parseGrade(value) {
  const text = String(value || "").trim();
  if (!text) return { valid: false, empty: true, text };
  if (!GRADE_INPUT_PATTERN.test(text)) return { valid: false, empty: false, text };
  const number = Number(text);
  if (!Number.isFinite(number) || number < 0 || number > 100) return { valid: false, empty: false, text };
  return { valid: true, empty: false, text, value: number };
}

function gradeEligibility(scholarship, gwaText, lowestText, remarkChecked) {
  if (!scholarship || scholarship.minGwa == null || scholarship.minLowest == null) {
    return { eligible: true, checked: false, tone: "", message: "" };
  }
  if (remarkChecked) {
    return { eligible: false, checked: true, tone: "bad", message: "Applicants with a failing grade, INC, or dropped subject are not eligible." };
  }
  const gwa = parseGrade(gwaText);
  const lowest = parseGrade(lowestText);
  if (gwa.empty || lowest.empty) {
    return { eligible: false, checked: true, tone: "", message: `Enter your GWA and lowest grade (0 to 100, up to 2 decimals) to check the ${scholarship.key} requirements.` };
  }
  if (!gwa.valid || !lowest.valid) {
    return { eligible: false, checked: true, tone: "bad", message: "Grades must be numbers from 0 to 100 with at most 2 decimal places." };
  }
  if (lowest.value > gwa.value) {
    return { eligible: false, checked: true, tone: "bad", message: "Your lowest grade cannot be higher than your GWA." };
  }
  if (gwa.value < scholarship.minGwa) {
    return { eligible: false, checked: true, tone: "bad", message: `Your GWA of ${gwa.text} is below the ${scholarship.minGwa} required for ${scholarship.key}.` };
  }
  if (lowest.value < scholarship.minLowest) {
    return { eligible: false, checked: true, tone: "bad", message: `Your lowest grade of ${lowest.text} is below the ${scholarship.minLowest} required for ${scholarship.key}.` };
  }
  return { eligible: true, checked: true, tone: "ok", message: `You meet the grade requirements for ${scholarship.key}.` };
}

function renderEligibilityNotice(element, state) {
  if (!state.checked) {
    element.hidden = true;
    element.textContent = "";
    element.className = "notice";
    return;
  }
  element.hidden = false;
  element.className = state.tone ? `notice ${state.tone}` : "notice";
  element.textContent = state.message;
}

async function startPage() {
  currentUser = await requireRole(["student"]);
  if (!currentUser) return;
  initSidebar(currentUser, "scholarships");
  currentTermApplications = await getActiveApplicationsForStudent(currentUser.id);
  const terms = await getAcademicTerms();
  applicationTerm = terms.find((term) => term.state === "Current");
  termScholarships = applicationTerm.scholarships.map((item) => ({ ...getScholarshipInfo(item.key), ...item }));
  const blocked = programNotOffered(currentUser.program, applicationTerm.trimester);
  el("programGrid").insertAdjacentHTML("beforebegin", `<div class="notice notice-spaced"><span>You are applying for ${escapeHtml(applicationTerm.label.replace(", AY ", " · AY "))}${blocked ? "<br>Your program has no 3rd trimester. Applications reopen next academic year." : ""}</span></div>`);
  el("programGrid").innerHTML = termScholarships.map(programCardHtml).join("");
  el("programGrid").addEventListener("click", (e) => {
    const button = e.target.closest("[data-program]");
    if (button) openProgramModal(button.dataset.program);
  });
  el("startApplicationBtn").addEventListener("click", openApplyModal);
  el("applyForm").addEventListener("submit", handleApplicationSubmit);
  const requested = getQueryParam("view");
  if (requested && getScholarshipInfo(requested)) openProgramModal(requested);
}

function openProgramModal(key) {
  selectedScholarship = termScholarships.find((item) => item.key === key);
  if (!selectedScholarship) return;
  const noticeText =
    "The application checks the GWA, lowest-grade and grade-remark information you enter. Authorized Staff verify it against your uploaded documents and make the final scholarship decision.";
  const deadline = scholarshipDeadlineInfo(selectedScholarship);
  el("programModalTitle").textContent = selectedScholarship.key;
  el("programModalBody").innerHTML = `
    <span class="micro">University program</span>
    <p class="modal-text modal-text-spaced">${selectedScholarship.description}</p>

    <dl class="detail-list">
      <dt>Benefit</dt><dd>${escapeHtml(selectedScholarship.benefit)}</dd>
      <dt>Deadline</dt><dd>${deadline.label ? `<span class="badge ${deadline.closed ? "badge-rejected" : "badge-submitted"}">${deadline.label}</span>` : escapeHtml(deadline.text)}</dd>
    </dl>

    <h3 class="modal-subhead">Eligibility</h3>
    <ul class="bullet-list">${selectedScholarship.eligibility.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>

    <h3 class="modal-subhead">Requirements</h3>
    <ul class="bullet-list">${SCHOLARSHIP_REQUIREMENTS.map((item) => `<li>${item.label}</li>`).join("")}</ul>

    <h3 class="modal-subhead">Check my eligibility</h3>
    <div class="form-row">
      <div class="form-group">
        <label for="quickGwa">GWA</label>
        <div class="input-wrap"><i class="ti ti-award"></i><input type="text" id="quickGwa" inputmode="decimal" placeholder="e.g. 88.25" autocomplete="off" /></div>
      </div>
      <div class="form-group">
        <label for="quickLowest">Lowest grade</label>
        <div class="input-wrap"><i class="ti ti-calculator"></i><input type="text" id="quickLowest" inputmode="decimal" placeholder="e.g. 86" autocomplete="off" /></div>
      </div>
    </div>
    <div class="notice" id="quickEligibilityNotice" hidden></div>

    <div class="notice notice-spaced">
      <i class="ti ti-info-circle"></i>
      <span>${noticeText}</span>
    </div>`;
  const existing = currentTermApplications.find(
    (app) => app.scholarshipType === selectedScholarship.key && !app.deleted
  );
  const blocked = programNotOffered(currentUser.program, applicationTerm.trimester);
  const button = el("startApplicationBtn");
  const note = el("appliedNote");
  note.hidden = true;
  note.innerHTML = "";
  if (existing) {
    button.disabled = true;
    button.textContent = "Already applied this term";
    note.innerHTML = `You already have a ${statusBadge(existing.status)} application for this scholarship this term. <a class="text-link" href="my-applications.html?view=${existing.id}">View my application <i class="ti ti-arrow-right"></i></a>`;
    note.hidden = false;
  } else {
    const scholarshipClosed = selectedScholarship.effectiveStatus === "Closed";
    button.disabled = scholarshipClosed || blocked;
    button.textContent = scholarshipClosed ? "Closed" : blocked ? "Applications reopen next academic year" : "Apply now";
  }
  const syncQuickCheck = () =>
    renderEligibilityNotice(
      el("quickEligibilityNotice"),
      gradeEligibility(selectedScholarship, el("quickGwa").value, el("quickLowest").value, false)
    );
  el("quickGwa").value = "";
  el("quickLowest").value = "";
  el("quickGwa").oninput = syncQuickCheck;
  el("quickLowest").oninput = syncQuickCheck;
  syncQuickCheck();
  openModal("programModal");
}

function openApplyModal() {
  if (selectedScholarship.effectiveStatus === "Closed" || programNotOffered(currentUser.program, applicationTerm.trimester)) return;
  el("applyProgram").innerHTML = programOptions(currentUser.program);
  closeModal("programModal");
  chosenFiles = {};
  chosenFileObjects = {};
  el("applyForm").reset();
  hideAlert("applyAlert");
  clearFieldErrors(["applyProgramError", "applyYearError", "applyDocsError", "applyConsentError", ...APPLY_GRADE_ERROR_IDS]);
  renderEligibilityNotice(el("applyEligibilityNotice"), { eligible: false, checked: false, tone: "", message: "" });
  el("applyScholarshipName").textContent = selectedScholarship.key;
  el("applicantInfo").innerHTML = `
    <dt>Full name</dt><dd>${escapeHtml(currentUser.fullName)}</dd>
    <dt>Student ID</dt><dd>${escapeHtml(currentUser.studentId)}</dd>
    <dt>University email</dt><dd>${escapeHtml(currentUser.email)}</dd>`;
  el("applyProgram").value = currentUser.program || "";
  el("applyYearLevel").value = currentUser.yearLevel || "";
  el("documentRows").innerHTML = INITIAL_SCHOLARSHIP_REQUIREMENTS.map((item) => {
    return `
    <div class="document-row">
      <i class="ti ti-file-text"></i>
      <div class="document-info">
        <strong>${item.label}</strong>
        <small id="fileStatus-${item.key}">No file selected &middot; PDF, JPG or PNG, up to ${MAX_FILE_SIZE_MB} MB</small>
      </div>
      <label class="btn btn-outline btn-sm">Choose file
        <input type="file" data-requirement="${item.key}" accept=".pdf,.jpg,.jpeg,.png" hidden />
      </label>
    </div>`;
  }).join("");
  el("documentRows").querySelectorAll("input[type=file]").forEach((input) => {
    input.addEventListener("change", () => handleFileChosen(input));
  });
  const submit = el("applyForm").querySelector("button[type=submit]");
  function checkProgramTerm() {
    return programNotOffered(val("applyProgram"), applicationTerm.trimester);
  }
  function syncApplyEligibility() {
    const state = gradeEligibility(
      selectedScholarship,
      el("applyGwa").value,
      el("applyLowest").value,
      el("applyFailingGrade").checked || el("applyIncompleteGrade").checked || el("applyDroppedGrade").checked
    );
    renderEligibilityNotice(el("applyEligibilityNotice"), state);
    const termBlocked = checkProgramTerm();
    submit.disabled = termBlocked || !state.eligible;
    submit.title = termBlocked ? "Your program has no 3rd trimester. Applications reopen next academic year." : "";
  }
  el("applyProgram").onchange = syncApplyEligibility;
  el("applyGwa").oninput = syncApplyEligibility;
  el("applyLowest").oninput = syncApplyEligibility;
  el("applyFailingGrade").onchange = syncApplyEligibility;
  el("applyIncompleteGrade").onchange = syncApplyEligibility;
  el("applyDroppedGrade").onchange = syncApplyEligibility;
  syncApplyEligibility();
  openModal("applyModal");
}

function handleFileChosen(input) {
  const key = input.dataset.requirement;
  const status = el("fileStatus-" + key);
  const file = input.files[0];
  if (!file) return;
  const check = validateFile(file);
  if (!check.valid) {
    status.textContent = check.message;
    status.className = "bad";
    delete chosenFiles[key];
    delete chosenFileObjects[key];
    input.value = "";
    return;
  }
  chosenFiles[key] = { name: file.name, uploadedAt: new Date().toISOString() };
  chosenFileObjects[key] = file;
  status.textContent = file.name + " \u00B7 Selected";
  status.className = "ok";
}

async function handleApplicationSubmit(e) {
  e.preventDefault();
  hideAlert("applyAlert");
  clearFieldErrors(["applyProgramError", "applyYearError", "applyDocsError", "applyConsentError", ...APPLY_GRADE_ERROR_IDS]);
  const program = val("applyProgram");
  const yearLevel = el("applyYearLevel").value;
  if (programNotOffered(program, applicationTerm.trimester) || programNotOffered(currentUser.program, applicationTerm.trimester)) {
    showAlert("applyAlert", "Your program has no 3rd trimester. Applications reopen next academic year.");
    return;
  }
  let hasError = false;
  const programCheck = checkLettersOnly(program, "Degree program");
  if (!programCheck.valid) {
    showFieldError("applyProgramError", programCheck.message);
    hasError = true;
  }
  if (!yearLevel) {
    showFieldError("applyYearError", "Please select your year level.");
    hasError = true;
  }
  const gwaResult = parseGrade(el("applyGwa").value);
  const lowestResult = parseGrade(el("applyLowest").value);
  const hasFailingGrade = el("applyFailingGrade").checked;
  const hasIncompleteGrade = el("applyIncompleteGrade").checked;
  const hasDroppedGrade = el("applyDroppedGrade").checked;
  if (gwaResult.empty) {
    showFieldError("applyGwaError", "GWA is required.");
    hasError = true;
  } else if (!gwaResult.valid) {
    showFieldError("applyGwaError", "GWA must be a number from 0 to 100 with at most 2 decimal places.");
    hasError = true;
  }
  if (lowestResult.empty) {
    showFieldError("applyLowestError", "Lowest grade is required.");
    hasError = true;
  } else if (!lowestResult.valid) {
    showFieldError("applyLowestError", "Lowest grade must be a number from 0 to 100 with at most 2 decimal places.");
    hasError = true;
  }
  if (gwaResult.valid && lowestResult.valid && lowestResult.value > gwaResult.value) {
    showFieldError("applyLowestError", "Lowest grade cannot be higher than your GWA.");
    hasError = true;
  }
  if (hasFailingGrade || hasIncompleteGrade || hasDroppedGrade) {
    showFieldError("applyRemarksError", "Applicants with a failing grade, INC, or dropped remark are not eligible.");
    hasError = true;
  }
  if (gwaResult.valid && selectedScholarship.minGwa != null && gwaResult.value < selectedScholarship.minGwa) {
    showFieldError("applyGwaError", `${selectedScholarship.key} requires a GWA of at least ${selectedScholarship.minGwa}.`);
    hasError = true;
  }
  if (lowestResult.valid && selectedScholarship.minLowest != null && lowestResult.value < selectedScholarship.minLowest) {
    showFieldError("applyLowestError", `${selectedScholarship.key} requires no grade below ${selectedScholarship.minLowest}.`);
    hasError = true;
  }
  const missing = INITIAL_SCHOLARSHIP_REQUIREMENTS.filter((item) => !chosenFiles[item.key]);
  if (missing.length) {
    showFieldError("applyDocsError", `Missing required document(s): ${missing.map((item) => item.label).join(", ")}.`);
    hasError = true;
  }
  if (!el("applyConsent").checked) {
    showFieldError("applyConsentError", "Please confirm that your information and documents are correct.");
    hasError = true;
  }
  if (hasError) {
    showAlert("applyAlert", "Please fix the items below before submitting.");
    return;
  }
  const button = el("applyForm").querySelector("button[type=submit]");
  button.disabled = true;
  button.innerHTML = '<i class="ti ti-loader-2"></i> Uploading...';
  const uploadedPaths = [];
  try {
    const applicationId = newId();
    const documents = {};
    for (const item of INITIAL_SCHOLARSHIP_REQUIREMENTS) {
      const file = chosenFileObjects[item.key];
      const path = storagePathFor(currentUser.id, applicationId, item.key, file.name);
      uploadedPaths.push(path);
      const storedPath = await uploadStoredFile(path, file);
      documents[item.key] = {
        name: file.name,
        path: storedPath,
        uploadedAt: chosenFiles[item.key].uploadedAt,
        sizeBytes: file.size,
        mimeType: fileMimeType(file),
      };
    }
    const application = await createApplication({
      id: applicationId,
      termId: applicationTerm.id,
      program,
      yearLevel,
      scholarshipType: selectedScholarship.key,
      gwa: gwaResult.value,
      lowestGrade: lowestResult.value,
      hasFailingGrade,
      hasIncompleteGrade,
      hasDroppedGrade,
      documents,
    });
    setFlash(`Application ${application.code} submitted successfully for ${applicationTermLabel(application)}! Your earlier applications were kept.`);
    window.location.href = "my-applications.html";
  } catch (error) {
    try {
      if (uploadedPaths.length) await discardStoredFiles(uploadedPaths);
    } catch (cleanupError) {
      console.error(cleanupError);
    }
    console.error(error);
    showAlert("applyAlert", friendlyError(error));
    button.disabled = false;
    button.innerHTML = '<i class="ti ti-send"></i> Submit application';
  }
}
