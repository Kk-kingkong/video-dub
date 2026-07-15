const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function extractBracedBody(source, marker) {
  const markerIndex = source.indexOf(marker);
  assert.ok(markerIndex >= 0, `missing ${marker}`);
  const start = source.indexOf("{", markerIndex);
  assert.ok(start >= 0, `missing object body for ${marker}`);

  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === quote) {
        quote = "";
      }
      continue;
    }

    if (char === "\"" || char === "'" || char === "`") {
      quote = char;
    } else if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start + 1, index);
      }
    }
  }

  throw new Error(`unterminated object for ${marker}`);
}

function extractObjectKeys(source, constName) {
  const body = extractBracedBody(source, `const ${constName} =`);
  return Array.from(body.matchAll(/^  (?:"([^"]+)"|([A-Za-z_$][\w$-]*)):\s*{/gm), (match) => match[1] || match[2]).sort();
}

function extractProviderOptionIds(source) {
  const marker = "const PROVIDER_OPTIONS = [";
  const markerIndex = source.indexOf(marker);
  assert.ok(markerIndex >= 0, "missing content PROVIDER_OPTIONS fallback");
  const start = source.indexOf("[", markerIndex);
  const end = source.indexOf("];", start);
  assert.ok(end > start, "unterminated content PROVIDER_OPTIONS fallback");
  return Array.from(source.slice(start, end).matchAll(/\["([^"]+)"/g), (match) => match[1]).sort();
}

function extractDefaultSetting(source, settingName) {
  const body = extractBracedBody(source, "const DEFAULT_SETTINGS =");
  const match = new RegExp(`${settingName}:\\s*"([^"]+)"`).exec(body);
  assert.ok(match, `missing DEFAULT_SETTINGS.${settingName}`);
  return match[1];
}

const background = read("extension/background.js");
const popup = read("extension/popup.js");
const content = read("extension/content.js");

const backgroundProviders = extractObjectKeys(background, "PROVIDERS");
const popupProviders = extractObjectKeys(popup, "PROVIDER_DEFAULTS");
const contentProviders = extractProviderOptionIds(content);
const userFacingBackgroundProviders = backgroundProviders.filter((id) => id !== "local-http");
const backgroundTranscriptionProviders = extractObjectKeys(background, "TRANSCRIPTION_PROVIDERS");
const popupTranscriptionProviders = extractObjectKeys(popup, "TRANSCRIPTION_PROVIDER_DEFAULTS");
const backgroundDefaultProvider = extractDefaultSetting(background, "provider");
const popupDefaultProvider = extractDefaultSetting(popup, "provider");
const contentDefaultProvider = extractDefaultSetting(content, "provider");
const backgroundDefaultTranscriptionProvider = extractDefaultSetting(background, "transcriptionProvider");
const popupDefaultTranscriptionProvider = extractDefaultSetting(popup, "transcriptionProvider");
const contentDefaultTranscriptionProvider = extractDefaultSetting(content, "transcriptionProvider");

assert.deepEqual(popupProviders, backgroundProviders, "popup provider defaults must match background provider registry");
assert.deepEqual(contentProviders, userFacingBackgroundProviders, "content provider fallback must match user-facing provider registry");
assert.deepEqual(
  popupTranscriptionProviders,
  backgroundTranscriptionProviders,
  "popup transcription defaults must match background transcription registry"
);

assert.ok(backgroundProviders.includes(backgroundDefaultProvider), "default provider must exist");
assert.equal(popupDefaultProvider, backgroundDefaultProvider, "popup default provider must match background");
assert.equal(contentDefaultProvider, backgroundDefaultProvider, "content default provider must match background");
assert.ok(
  backgroundTranscriptionProviders.includes(backgroundDefaultTranscriptionProvider),
  "default transcription provider must exist"
);
assert.equal(
  popupDefaultTranscriptionProvider,
  backgroundDefaultTranscriptionProvider,
  "popup default transcription provider must match background"
);
assert.equal(
  contentDefaultTranscriptionProvider,
  backgroundDefaultTranscriptionProvider,
  "content default transcription provider must match background"
);
assert.match(popup, /Object\.entries\(TRANSCRIPTION_PROVIDER_DEFAULTS\)\s*\.map/);

assert.match(background, /providers: getProviderList\(\)/);
assert.match(background, /transcriptionProviders: getTranscriptionProviderList\(\)/);
assert.match(popup, /function applyProviderRegistry/);
assert.match(popup, /function renderProviderOptions/);
assert.match(content, /function updateProviderOptionsFromResponse/);

console.log("provider registry checks ok");
