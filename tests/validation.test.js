const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("PU scholarship system/js/validation.js", "utf8");
const context = vm.createContext({});
vm.runInContext(source + `
  globalThis.results = {
    years: ["2026-2027", "2026/2027", "2026–2027"].map(checkAcademicYear),
    normalized: normalizeAcademicYear("2026–2027"),
    invalidYear: checkAcademicYear("2026-2028"),
    emptyFile: validateFile({ name: "grades.pdf", size: 0 }),
    validFile: validateFile({ name: "grades.pdf", size: 12 }),
    oversizedFile: validateFile({ name: "grades.pdf", size: 6 * 1024 * 1024 }),
    badFile: validateFile({ name: "grades.exe", size: 12 }),
    password: validatePassword("Validpass1!"),
  };
`, context);
assert(context.results.years.every((item) => item.valid));
assert.strictEqual(context.results.normalized, "2026–2027");
assert.strictEqual(context.results.invalidYear.valid, false);
assert.strictEqual(context.results.emptyFile.valid, false);
assert.strictEqual(context.results.validFile.valid, true);
assert.strictEqual(context.results.oversizedFile.valid, false);
assert.strictEqual(context.results.badFile.valid, false);
assert.strictEqual(context.results.password.valid, true);

// The signed-upload request must advertise the canonical MIME type before the
// file part. Some browsers report a wrong File.type for a .jpg download.
(async () => {
  class FakeFile {
    constructor(parts, name, options = {}) {
      this.parts = parts;
      this.name = name;
      this.type = options.type || "";
      this.size = options.size || 0;
    }
  }
  class FakeFormData {
    constructor() {
      this.entries = [];
    }
    append(name, value, fileName) {
      this.entries.push({ name, value, fileName });
    }
  }
  const requests = [];
  let uploadedForm = null;
  const filesContext = vm.createContext({
    File: FakeFile,
    FormData: FakeFormData,
    apiRequest: async (path, options) => {
      requests.push({ path, options });
      return { signedUrl: "https://storage.example/upload", path: "user/app/copyOfGrades/file_asus.jpg" };
    },
    fetch: async (url, options) => {
      uploadedForm = options.body;
      return { ok: true, json: async () => ({}) };
    },
  });
  const filesSource = fs.readFileSync("PU scholarship system/js/files.js", "utf8");
  vm.runInContext(`${filesSource}
    const original = new File(["image bytes"], "asus.jpg", { type: "image/webp", size: 42 });
    globalThis.uploadPromise = uploadStoredFile("user/app/copyOfGrades/file_asus.jpg", original);
  `, filesContext);
  await filesContext.uploadPromise;
  assert.strictEqual(requests[0].options.body.contentType, "image/jpeg");
  assert.deepStrictEqual(uploadedForm.entries.map((entry) => entry.name), ["cacheControl", "contentType", ""]);
  assert.strictEqual(uploadedForm.entries[1].value, "image/jpeg");
  assert.strictEqual(uploadedForm.entries[2].value.type, "image/jpeg");
})().then(() => {
  console.log("Browser validation and upload regression checks passed");
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
