const PROGRAMS = [
  { name: "BS Nursing", terms: 2 },
  { name: "Placeholder Program A", terms: 3 },
  { name: "Placeholder Program B", terms: 3 },
];

const BENEFIT_TEXT = "Benefits to be confirmed by the CSS Office";
const DEADLINE_TEXT = "To be announced";

const SCHOLARSHIP_CATALOG = [
  {
    key: "Academic Scholarship",
    icon: "ti-school",
    description: "Awarded to students who consistently demonstrate strong academic performance.",
    eligibility: [
      "Currently enrolled Panpacific University student",
      "GWA of at least 87, with no grade below 85",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "Entrance Exam Scholarship",
    icon: "ti-clipboard-text",
    description: "Awarded to incoming students based on their performance in the university entrance examination.",
    eligibility: [
      "Qualifying score in the Panpacific University entrance examination",
      "Incoming freshman or transferee student",
      "Complete admission requirements on file",
      "GWA of at least 87, with no grade below 85",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "4Ps Scholarship",
    icon: "ti-heart-handshake",
    description: "Support for students from households enrolled in the government's 4Ps program.",
    eligibility: [
      "Household listed under the 4Ps program",
      "Valid 4Ps household ID or certificate",
      "Currently enrolled or incoming Panpacific University student",
      "GWA of at least 85, with no grade below 82",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "Urdanetarian Scholarship",
    icon: "ti-building-community",
    description: "For qualified residents of Urdaneta City in recognition of local community ties.",
    eligibility: [
      "Proof of residency in Urdaneta City",
      "GWA of at least 85, with no grade below 82",
      "No failing grade, INC, or dropped remarks",
      "Certificate of residency or barangay clearance",
    ],
  },
  {
    key: "RPSEA Scholarship",
    icon: "ti-award",
    description: "Awarded under the RPSEA scholarship program to qualified applicants.",
    eligibility: [
      "Meets RPSEA program qualification criteria",
      "Complete supporting documentation",
      "GWA of at least 85, with no grade below 82",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "SOC Scholarship",
    icon: "ti-users-group",
    description: "Sponsored scholarship offered under the SOC scholarship program.",
    eligibility: [
      "Meets SOC program qualification criteria",
      "Currently enrolled Panpacific University student",
      "Complete supporting documentation",
      "GWA of at least 85, with no grade below 82",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "BSA Scholarship",
    icon: "ti-calculator",
    description: "Awarded to qualified students under the BSA scholarship program.",
    eligibility: [
      "Meets BSA program qualification criteria",
      "GWA of at least 85, with no grade below 82",
      "Complete supporting documentation",
      "No failing grade, INC, or dropped remarks",
    ],
  },
  {
    key: "New Program Scholarship",
    icon: "ti-sparkles",
    description: "Incentive scholarship for students enrolling in newly opened Panpacific University programs.",
    eligibility: [
      "Enrolled in a qualified new academic program",
      "Complete admission requirements",
      "GWA of at least 85, with no grade below 82",
      "No failing grade, INC, or dropped remarks",
    ],
  },
];

// Stage 1: required in the initial application form.
const INITIAL_SCHOLARSHIP_REQUIREMENTS = [
  { key: "copyOfGrades", label: "Copy of Grades" },
];

// Stage 2: uploaded by the student after the application is Approved,
// then reviewed by staff with the 3-attempt system.
const POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS = [
  { key: "letterOfIntent", label: "Letter of Intent" },
  { key: "notarizedAgreement", label: "Notarized Scholarship Agreement" },
];

// Full list, still used for viewer labels and the student checklist.
const SCHOLARSHIP_REQUIREMENTS = [
  ...INITIAL_SCHOLARSHIP_REQUIREMENTS,
  ...POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS,
];

const SCHOLARSHIP_AGREEMENT_TEMPLATES = {
  "Academic Scholarship": "assets/documents/academic-entrance-exam-scholarship-agreement.pdf",
  "Entrance Exam Scholarship": "assets/documents/academic-entrance-exam-scholarship-agreement.pdf",
  "4Ps Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
  "Urdanetarian Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
  "RPSEA Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
  "SOC Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
  "BSA Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
  "New Program Scholarship": "assets/documents/4ps-urdanetarian-rpsea-soc-bsa-new-program-scholarship-agreement.pdf",
};

function getScholarshipInfo(key) {
  return SCHOLARSHIP_CATALOG.find((s) => s.key === key) || null;
}

const PROGRAM_COLORS = ["green", "peach", "blue"];

function programCardHtml(scholarship) {
  const color = PROGRAM_COLORS[SCHOLARSHIP_CATALOG.findIndex((item) => item.key === scholarship.key) % PROGRAM_COLORS.length];
  const deadline = scholarshipDeadlineInfo(scholarship);
  return `
    <article class="card hover-lift program-card">
      <div class="program-card-top">
        <div class="program-icon ${color}"><i class="ti ${scholarship.icon}"></i></div>
        <span class="badge ${deadline.closed ? "badge-rejected" : "badge-approved"}">${scholarship.effectiveStatus || scholarship.status || "Open"}</span>
      </div>
      <h3>${scholarship.key}</h3>
      <p>${scholarship.description}</p>
      <div class="benefit"><i class="ti ti-gift"></i> ${escapeHtml(scholarship.benefit || BENEFIT_TEXT)}</div>
      <div class="program-bottom">
        ${deadline.label ? `<span class="badge ${deadline.closed ? "badge-rejected" : "badge-submitted"}">${deadline.label}</span>` : `<span>Deadline: ${escapeHtml(deadline.text)}</span>`}
        <button type="button" class="program-open" data-program="${scholarship.key}" aria-label="View ${scholarship.key}"><i class="ti ti-arrow-up-right"></i></button>
      </div>
    </article>`;
}
