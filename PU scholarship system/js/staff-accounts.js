let currentUser = null;
let accountList = [];
let activeRoleGroup = "staff";
let editingId = null;
let deletingId = null;

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["admin"]);
  if (!currentUser) return;
  initSidebar(currentUser, "accounts");
  el("newAcctHint").textContent = PASSWORD_HINT_TEXT;
  await showAccounts();
  el("roleTabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab-btn");
    if (!tab) return;
    el("roleTabs").querySelectorAll(".tab-btn").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    activeRoleGroup = tab.dataset.roleGroup;
    renderAccounts();
  });
  el("openAddAccountBtn").addEventListener("click", () => {
    el("addAccountForm").reset();
    hideAlert("newAcctAlert");
    clearFieldErrors(["newAcctNameError", "newAcctEmailError", "newAcctPasswordError", "newAcctConfirmError"]);
    openModal("addAccountModal");
  });
  el("addAccountForm").addEventListener("submit", handleCreateAccount);
  el("editAcctHint").textContent = PASSWORD_HINT_TEXT;
  el("accountRows").addEventListener("click", (e) => {
    const editButton = e.target.closest("[data-edit-account]");
    if (editButton) openEditAccount(editButton.dataset.editAccount);
    const deleteButton = e.target.closest("[data-delete-account]");
    if (deleteButton) askToDeleteAccount(deleteButton.dataset.deleteAccount);
  });
  el("editAccountForm").addEventListener("submit", handleEditAccount);
  el("deleteAcctConfirmBtn").addEventListener("click", () => runPage(confirmDeleteAccount));
}

async function showAccounts() {
  accountList = await allStaffAccounts();
  renderAccounts();
}

function renderAccounts() {
  const accounts = accountList.filter((account) => (activeRoleGroup === "students" ? account.role === "student" : account.role !== "student"));
  el("accountRows").innerHTML = accounts
    .map((account) => {
      const isSelf = account.id === currentUser.id;
      return `
    <tr>
      <td data-label="Full name">${escapeHtml(account.fullName)} ${isSelf ? '<span class="you-badge">You</span>' : ""}</td>
      <td data-label="Email">${escapeHtml(account.email)}</td>
      <td data-label="Role"><span class="badge badge-role-${account.role}">${account.role === "staff" ? "Authorized staff" : account.role}</span></td>
      <td data-label="Created">${formatDate(account.createdAt)}</td>
      <td data-label="">
        <div class="row-actions">
          <button type="button" class="btn btn-outline btn-sm" data-edit-account="${account.id}"><i class="ti ti-pencil"></i> Edit</button>
          ${isSelf ? "" : `<button type="button" class="btn btn-danger btn-sm" data-delete-account="${account.id}"><i class="ti ti-trash"></i> Delete</button>`}
        </div>
      </td>
    </tr>`;
    })
    .join("");
}

async function handleCreateAccount(e) {
  e.preventDefault();
  clearFieldErrors(["newAcctNameError", "newAcctEmailError", "newAcctPasswordError", "newAcctConfirmError"]);
  hideAlert("newAcctAlert");
  const fullName = val("newAcctName");
  const email = val("newAcctEmail");
  const role = el("newAcctRole").value;
  const password = el("newAcctPassword").value;
  const confirmPassword = el("newAcctConfirm").value;
  let hasError = false;
  const nameCheck = checkLettersOnly(fullName, "Full name");
  if (!nameCheck.valid) {
    showFieldError("newAcctNameError", nameCheck.message);
    hasError = true;
  }
  if (!email) {
    showFieldError("newAcctEmailError", "University email is required.");
    hasError = true;
  } else if (!isUniversityEmail(email)) {
    showFieldError("newAcctEmailError", `Only ${UNIVERSITY_EMAIL_DOMAIN} email addresses are accepted.`);
    hasError = true;
  }
  const passwordCheck = validatePassword(password);
  if (!passwordCheck.valid) {
    showFieldError("newAcctPasswordError", passwordCheck.message);
    hasError = true;
  }
  if (password !== confirmPassword) {
    showFieldError("newAcctConfirmError", "Passwords do not match.");
    hasError = true;
  }
  if (hasError) return;
  const button = el("addAccountForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Creating account...");
  const result = await createStaffAccount({ role, fullName, email, password });
  clearButtonBusy(button);
  if (result.error) {
    showAlert("newAcctAlert", result.error);
    return;
  }
  closeModal("addAccountModal");
  showToast(`${role === "admin" ? "Admin" : "Authorized Staff"} account created for ${fullName}.`);
  await runPage(showAccounts);
}


const EDIT_ERROR_IDS = ["editAcctNameError", "editAcctEmailError", "editAcctPasswordError", "editAcctConfirmError"];

function openEditAccount(id) {
  const account = accountList.find((item) => item.id === id);
  if (!account) return;
  editingId = id;
  el("editAccountForm").reset();
  hideAlert("editAcctAlert");
  clearFieldErrors(EDIT_ERROR_IDS);
  el("editAcctName").value = account.fullName;
  el("editAcctEmail").value = account.email;
  el("editAcctRole").value = account.role;
  const isSelf = id === currentUser.id;
  el("editAcctRole").disabled = isSelf;
  el("editAcctRoleHint").textContent = isSelf ? "You cannot change your own role." : "";
  openModal("editAccountModal");
}

async function handleEditAccount(e) {
  e.preventDefault();
  clearFieldErrors(EDIT_ERROR_IDS);
  hideAlert("editAcctAlert");
  const fullName = val("editAcctName");
  const email = val("editAcctEmail");
  const role = el("editAcctRole").value;
  const password = el("editAcctPassword").value;
  const confirmPassword = el("editAcctConfirm").value;
  let hasError = false;
  const nameCheck = checkLettersOnly(fullName, "Full name");
  if (!nameCheck.valid) {
    showFieldError("editAcctNameError", nameCheck.message);
    hasError = true;
  }
  if (!email) {
    showFieldError("editAcctEmailError", "University email is required.");
    hasError = true;
  } else if (!isUniversityEmail(email)) {
    showFieldError("editAcctEmailError", `Only ${UNIVERSITY_EMAIL_DOMAIN} email addresses are accepted.`);
    hasError = true;
  }
  if (password || confirmPassword) {
    const passwordCheck = validatePassword(password);
    if (!passwordCheck.valid) {
      showFieldError("editAcctPasswordError", passwordCheck.message);
      hasError = true;
    }
    if (password !== confirmPassword) {
      showFieldError("editAcctConfirmError", "Passwords do not match.");
      hasError = true;
    }
  }
  if (hasError) return;
  const button = el("editAccountForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Saving changes...");
  const result = await updateStaffAccount(editingId, { fullName, email, role, password });
  clearButtonBusy(button);
  if (result.error) {
    showAlert("editAcctAlert", result.error);
    return;
  }
  closeModal("editAccountModal");
  showToast(`Account for ${fullName} updated.`);
  if (editingId === currentUser.id) currentUser = await getCurrentUser();
  editingId = null;
  await runPage(showAccounts);
}

function askToDeleteAccount(id) {
  const account = accountList.find((item) => item.id === id);
  if (!account) return;
  deletingId = id;
  hideAlert("deleteAcctAlert");
  const roleName = account.role === "admin" ? "Admin" : account.role === "staff" ? "Authorized Staff" : "Student";
  el("deleteAcctText").textContent = `Are you sure you want to delete the ${roleName} account of ${account.fullName} (${account.email})? They will no longer be able to sign in, but their application records will be retained.`;
  openModal("deleteAccountModal");
}

async function confirmDeleteAccount() {
  const account = accountList.find((item) => item.id === deletingId);
  const button = el("deleteAcctConfirmBtn");
  hideAlert("deleteAcctAlert");
  setButtonBusy(button, "Deleting...");
  const result = await deleteStaffAccount(deletingId);
  clearButtonBusy(button);
  if (result.error) {
    showAlert("deleteAcctAlert", result.error);
    return;
  }
  deletingId = null;
  closeModal("deleteAccountModal");
  showToast(`Account${account ? " of " + account.fullName : ""} deleted.`);
  await runPage(showAccounts);
}
