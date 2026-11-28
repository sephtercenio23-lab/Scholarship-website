const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync("PU scholarship system/js/application-view.js", "utf8");

test("application details omit removed features even for older applications", () => {
  const context = vm.createContext({
    document: { addEventListener() {} },
    currentUser: { role: "student" },
    INITIAL_SCHOLARSHIP_REQUIREMENTS: [{ key: "copyOfGrades", label: "Copy of Grades" }],
    escapeHtml: (value) => String(value ?? ""),
    isApprovedStatus: (status) => status === "Approved",
    isStudentGradesApproved: (status) => status === "Approved (Grades)",
    isStudentScholarApproved: (status) => status === "Approved as a Scholar",
    isStudentApproved: (status) => ["Approved (Grades)", "Approved as a Scholar"].includes(status),
    isPendingApprovalStatus: () => false,
    isChangedAfterFinance: () => false,
    formatDate: () => "date",
    applicationTermLabel: (app) => app.term,
    applicationStatusBadges: () => "Approved",
    pastDiscountLabel: () => "—",
    APPROVAL_STAGES: [],
  });
  vm.runInContext(source, context);
  vm.runInContext('postApprovalDocsHtml = () => "Post-approval documents"; appealSectionHtml = () => "";', context);
  const html = context.applicationDetailsHtml({
    id: "app-id", code: "APP-1", status: "Approved", term: "Current term",
    dutyHours: 80, reportReceivedAt: "2026-01-01",
    documents: { copyOfGrades: { name: "grades.pdf" }, terminalReport: { name: "report.pdf" } },
  }, true);
  assert.match(html, /Copy of Grades/);
  assert.match(html, /Post-approval documents/);
  assert.doesNotMatch(html, /duty|terminal report|report\.pdf/i);
});

test("authorized staff can edit current-term tuition fee discount once endorsed by staff", () => {
  function renderFor(role, status, archived = false) {
    const context = vm.createContext({
      document: { addEventListener() {} },
      currentUser: { role },
      INITIAL_SCHOLARSHIP_REQUIREMENTS: [{ key: "copyOfGrades", label: "Copy of Grades" }],
      escapeHtml: (value) => String(value ?? ""),
      isApprovedStatus: (value) => ["Approved", "Approved by Executive President", "Sent to Finance", "Exported"].includes(value),
      isPendingApprovalStatus: (value) => ["Under Evaluation", "Endorsed by Staff", "Approved by President"].includes(value),
      isStudentGradesApproved: (value) => value === "Approved (Grades)",
      isStudentScholarApproved: (value) => value === "Approved as a Scholar",
      isStudentApproved: (value) => ["Approved (Grades)", "Approved as a Scholar"].includes(value),
      isChangedAfterFinance: () => false,
      formatDate: () => "Nov 27, 2026",
      applicationTermLabel: (app) => app.term,
      applicationStatusBadges: (app) => app.status,
      pastDiscountLabel: () => "75%",
      APPROVAL_STAGES: [],
    });
    vm.runInContext(source, context);
    vm.runInContext('postApprovalDocsHtml = () => ""; appealSectionHtml = () => "";', context);
    return context.applicationDetailsHtml(
      {
        id: "app-id",
        code: "APP-00011",
        status,
        archived,
        term: "1st Trimester, AY 2027\u20132028",
        documents: { copyOfGrades: { name: "grades.jpg" } },
      },
      true
    );
  }

  for (const status of ["Endorsed by Staff", "Approved by President", "Approved", "Sent to Finance"]) {
    assert.match(renderFor("staff", status, false), /data-discount-action="edit"/);
    assert.doesNotMatch(renderFor("staff", status, true), /data-discount-action="edit"/);
  }
  for (const status of ["Submitted", "Under Evaluation", "Rejected"]) {
    assert.doesNotMatch(renderFor("staff", status, false), /data-discount-action="edit"/);
  }
  for (const role of ["president", "executive_president", "student"]) {
    assert.doesNotMatch(renderFor(role, "Endorsed by Staff", false), /data-discount-action="edit"/);
  }

  const dataSource = readFileSync("PU scholarship system/js/data.js", "utf8");
  const commonSource = readFileSync("PU scholarship system/js/common.js", "utf8");
  const fullContext = vm.createContext({
    document: { addEventListener() {}, getElementById: () => null, querySelectorAll: () => [], documentElement: {} },
    window: { addEventListener() {} },
    sessionStorage: { getItem: () => null, removeItem() {} },
    MutationObserver: class { observe() {} },
    currentUser: { role: "staff" },
    INITIAL_SCHOLARSHIP_REQUIREMENTS: [{ key: "copyOfGrades", label: "Copy of Grades" }],
    pastDiscountLabel: () => "75%",
  });
  vm.runInContext(dataSource, fullContext);
  vm.runInContext(commonSource, fullContext);
  vm.runInContext(source, fullContext);
  vm.runInContext('postApprovalDocsHtml = () => ""; appealSectionHtml = () => "";', fullContext);
  assert.equal(fullContext.isDiscountEditableStatus("Endorsed by Staff"), true);
  assert.equal(fullContext.isDiscountEditableStatus("Under Evaluation"), false);
  const realHtml = fullContext.applicationDetailsHtml(
    {
      id: "app-id",
      code: "APP-00011",
      status: "Endorsed by Staff",
      archived: false,
      term: "1st Trimester, AY 2027\u20132028",
      documents: { copyOfGrades: { name: "grades.jpg" } },
    },
    true
  );
  assert.match(realHtml, /data-discount-action="edit"/);
});
