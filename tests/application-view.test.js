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
