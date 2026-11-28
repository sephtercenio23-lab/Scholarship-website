let currentUser = null;
let selectedScholarship = null;
let termScholarships = [];
let applicationTerm = null;
let currentTermApplications = [];
let chosenFiles = {};
let chosenFileObjects = {};

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["student"]);
  if (!currentUser) return;
  initSidebar(currentUser, "scholarships");
  let terms = [];
  [currentTermApplications, terms] = await Promise.all([
    getActiveApplicationsForStudent(currentUser.id),
    getAcademicTerms(),
  ]);
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
    <ul class="bullet-list">${SCHOLARSHIP_REQUIREMENTS.map((item) => `<li>${item.label}</li>`).join("")}</ul>`;
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
  openModal("programModal");
}

function openApplyModal() {
  if (selectedScholarship.effectiveStatus === "Closed" || programNotOffered(currentUser.program, applicationTerm.trimester)) return;
  closeModal("programModal");
  chosenFiles = {};
  chosenFileObjects = {};
  el("applyForm").reset();
  hideAlert("applyAlert");
  clearFieldErrors(["applyProgramError", "applyYearError", "applyPastDiscountError", "applyDocsError", "applyConsentError"]);
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
  clearFieldErrors(["applyProgramError", "applyYearError", "applyPastDiscountError", "applyDocsError", "applyConsentError"]);
  const program = currentUser.program || "";
  const yearLevel = el("applyYearLevel").value;
  if (programNotOffered(program, applicationTerm.trimester)) {
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
  const pastDiscount = el("applyPastDiscount").value;
  if (!PAST_DISCOUNT_OPTIONS.some((option) => option.value === pastDiscount)) {
    showFieldError("applyPastDiscountError", "Please select the tuition fee discount you had in the past term or academic year.");
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
  setButtonBusy(button, "Uploading...");
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
      pastDiscount,
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
    clearButtonBusy(button);
  }
}
