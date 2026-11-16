const resetEmail = sessionStorage.getItem("sams_reset_email");
if (!resetEmail) window.location.href = "index.html";

el("pinForm").addEventListener("submit", (e) => runPage(() => handlePin(e)));
el("resetForm").addEventListener("submit", (e) => runPage(() => handleReset(e)));
el("resetPasswordHint").textContent = PASSWORD_HINT_TEXT;

async function handlePin(e) {
  e.preventDefault();
  clearFieldErrors(["resetPinError"]);
  hideAlert("pinAlert");
  const pin = el("resetPin").value.trim();
  if (!/^\d{6}$/.test(pin)) {
    showFieldError("resetPinError", "Enter the 6-digit PIN from your email.");
    return;
  }
  const button = el("pinForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Checking PIN...");
  const result = await verifyResetPin(resetEmail, pin);
  if (result.error) {
    showAlert("pinAlert", result.error);
    clearButtonBusy(button);
    return;
  }
  el("pinForm").hidden = true;
  el("resetStepTitle").textContent = "Choose a new password.";
  el("resetIntro").textContent = "PIN verified. Choose a new password for your account.";
  el("resetForm").hidden = false;
  el("resetNew").focus();
}

async function handleReset(e) {
  e.preventDefault();
  clearFieldErrors(["resetNewError", "resetConfirmError"]);
  hideAlert("resetAlert");
  const newPassword = el("resetNew").value;
  const confirmPassword = el("resetConfirm").value;
  let hasError = false;
  const passwordCheck = validatePassword(newPassword);
  if (!passwordCheck.valid) {
    showFieldError("resetNewError", passwordCheck.message);
    hasError = true;
  }
  if (newPassword !== confirmPassword) {
    showFieldError("resetConfirmError", "Passwords do not match.");
    hasError = true;
  }
  if (hasError) return;
  const button = el("resetForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Updating password...");
  const result = await setNewPassword(resetEmail, newPassword);
  if (result.error) {
    showAlert("resetAlert", result.error);
    clearButtonBusy(button);
    return;
  }
  sessionStorage.removeItem("sams_reset_email");
  setFlash("Your password has been updated. Log in with your new password.");
  window.location.href = "index.html";
}