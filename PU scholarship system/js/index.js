runPage(async () => {
  if (await redirectIfLoggedIn()) return;
  el("loginForm").addEventListener("submit", handleLogin);
  el("forgotPasswordLink").addEventListener("click", openForgotModal);
  el("forgotForm").addEventListener("submit", handleForgot);
});

async function handleLogin(e) {
  e.preventDefault();
  hideAlert("loginAlert");
  const email = val("loginEmail");
  const password = el("loginPassword").value;
  if (!email || !password) {
    showAlert("loginAlert", "Please enter your email and password.");
    return;
  }
  const button = el("loginForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Logging in...");
  try {
    const result = await signIn(email, password);
    if (result.error) {
      showAlert("loginAlert", result.error);
      clearButtonBusy(button);
      return;
    }
    window.location.href = homePageFor(result.user);
  } catch (error) {
    showAlert("loginAlert", friendlyError(error));
    clearButtonBusy(button);
  }
}

function openForgotModal(e) {
  e.preventDefault();
  el("forgotForm").reset();
  clearFieldError("forgotEmailError");
  hideAlert("forgotAlert");
  el("forgotEmail").value = el("loginEmail").value;
  openModal("forgotModal");
}

async function handleForgot(e) {
  e.preventDefault();
  clearFieldError("forgotEmailError");
  hideAlert("forgotAlert");
  const email = val("forgotEmail");
  if (!email) return showFieldError("forgotEmailError", "University email is required.");
  if (!isUniversityEmail(email)) {
    return showFieldError("forgotEmailError", `Only ${UNIVERSITY_EMAIL_DOMAIN} email addresses are accepted.`);
  }
  const button = el("forgotForm").querySelector("button[type=submit]");
  setButtonBusy(button, "Sending...");
  try {
    const result = await sendPasswordReset(email);
    if (result.error) {
      showAlert("forgotAlert", result.error);
    } else {
      sessionStorage.setItem("sams_reset_email", email);
      window.location.href = "reset-password.html";
      return;
    }
  } catch (error) {
    showAlert("forgotAlert", friendlyError(error));
  }
  clearButtonBusy(button);
}