(function installLocalTubeHelpers(globalScope) {
  function addQuery(url, params) {
    const next = new URL(url);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        next.searchParams.set(key, value);
      }
    }
    return next.toString();
  }

  function limitCaptionTrackAttempts(rankedTracks, targetLanguage, options = {}) {
    const tracks = (Array.isArray(rankedTracks) ? rankedTracks : []).filter(Boolean);
    const targetIdentity = normalizeCaptionLanguage(targetLanguage);
    const maxTarget = clampInteger(options.maxTarget, 0, 4, 2);
    const maxSource = clampInteger(options.maxSource, 0, 4, 1);
    const targetTracks = [];
    const sourceTracks = [];

    for (const track of tracks) {
      const isTarget = Boolean(
        targetIdentity && normalizeCaptionLanguage(track.languageCode) === targetIdentity
      );
      if (isTarget && targetTracks.length < maxTarget) {
        targetTracks.push(track);
      } else if (!isTarget && sourceTracks.length < maxSource) {
        sourceTracks.push(track);
      }
    }

    return [...targetTracks, ...sourceTracks];
  }

  function makeCaptionFetchCandidates(baseUrl) {
    const rawUrl = String(baseUrl || "").trim();
    if (!rawUrl) {
      return [];
    }
    return Array.from(new Set([
      rawUrl,
      addQuery(rawUrl, { fmt: "json3" }),
      addQuery(rawUrl, { fmt: "vtt" })
    ]));
  }

  function pickCaptionTrack(tracks, preferredLanguage = "") {
    if (!Array.isArray(tracks) || !tracks.length) {
      return null;
    }

    const preferredIdentity = normalizeCaptionLanguage(preferredLanguage);
    if (preferredIdentity) {
      const preferredManual = tracks.find(
        (track) => normalizeCaptionLanguage(track.languageCode) === preferredIdentity && track.kind !== "asr"
      );
      const preferredAny = tracks.find((track) => normalizeCaptionLanguage(track.languageCode) === preferredIdentity);
      if (preferredManual || preferredAny) {
        return preferredManual || preferredAny;
      }
    }

    const englishManual = tracks.find((track) => normalizeLanguagePrefix(track.languageCode) === "en" && track.kind !== "asr");
    const firstManual = tracks.find((track) => track.kind !== "asr");
    return englishManual || firstManual || tracks[0];
  }

  function responseMatchesVideo(response, videoId) {
    if (!videoId) {
      return false;
    }

    if (response?.videoDetails?.videoId === videoId) {
      return true;
    }

    const tracks = response?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    return tracks.some((track) => {
      try {
        return new URL(track.baseUrl).searchParams.get("v") === videoId;
      } catch (error) {
        return String(track.baseUrl || "").includes(`v=${videoId}`);
      }
    });
  }

  function parseCaptionPayload(text) {
    const value = stripJsonProtectionPrefix(String(text || "").trim());
    if (!value) {
      return [];
    }

    if (value.startsWith("{")) {
      try {
        return parseJson3Captions(JSON.parse(value));
      } catch (error) {
        return [];
      }
    }

    if (/^WEBVTT/i.test(value)) {
      return parseVttCaptions(value);
    }

    return parseXmlCaptions(value);
  }

  function parseJson3Captions(data) {
    return (data?.events || [])
      .filter((event) => Array.isArray(event.segs) && event.segs.length)
      .map((event, index) => {
        const text = normalizeCaptionText(event.segs.map((seg) => seg.utf8 || "").join(""));
        const start = Number(event.tStartMs || 0) / 1000;
        const duration = Number(event.dDurationMs || 1800) / 1000;
        return {
          id: String(index),
          start,
          end: start + Math.max(duration, 0.8),
          text
        };
      })
      .filter((cue) => cue.text);
  }

  function parseXmlCaptions(xmlText) {
    if (typeof DOMParser !== "undefined") {
      const doc = new DOMParser().parseFromString(xmlText, "text/xml");
      const timedTextNodes = Array.from(doc.querySelectorAll("text"));
      if (timedTextNodes.length) {
        return timedTextNodes.map(readTimedTextNode).filter((cue) => cue.text);
      }

      return Array.from(doc.querySelectorAll("p")).map(readXmlParagraphNode).filter((cue) => cue.text);
    }

    const textNodes = readCaptionNodes(xmlText, "text").map(({ attrs, body }, index) =>
      normalizeCaptionCue(index, Number(attrs.start || 0), Number(attrs.dur || 1.8), stripCaptionMarkup(body))
    );
    if (textNodes.length) {
      return textNodes.filter((cue) => cue.text);
    }

    return readCaptionNodes(xmlText, "p")
      .map(({ attrs, body }, index) =>
        normalizeCaptionCue(
          index,
          readXmlParagraphStart(attrs),
          readXmlParagraphDuration(attrs),
          stripCaptionMarkup(body)
        )
      )
      .filter((cue) => cue.text);
  }

  function readTimedTextNode(node, index) {
    return normalizeCaptionCue(
      index,
      Number(node.getAttribute("start") || 0),
      Number(node.getAttribute("dur") || 1.8),
      node.textContent
    );
  }

  function readXmlParagraphNode(node, index) {
    const attrs = {
      t: node.getAttribute("t") || "",
      d: node.getAttribute("d") || "",
      begin: node.getAttribute("begin") || "",
      end: node.getAttribute("end") || "",
      dur: node.getAttribute("dur") || ""
    };
    return normalizeCaptionCue(
      index,
      readXmlParagraphStart(attrs),
      readXmlParagraphDuration(attrs),
      node.textContent
    );
  }

  function readXmlParagraphStart(attrs) {
    if (attrs.t !== undefined && attrs.t !== "") {
      return Number(attrs.t || 0) / 1000;
    }
    return parseTimedTextTimestamp(attrs.begin || 0);
  }

  function readXmlParagraphDuration(attrs) {
    if (attrs.d !== undefined && attrs.d !== "") {
      return Number(attrs.d || 1800) / 1000;
    }
    if (attrs.dur !== undefined && attrs.dur !== "") {
      return parseTimedTextTimestamp(attrs.dur);
    }
    const start = parseTimedTextTimestamp(attrs.begin || 0);
    const end = parseTimedTextTimestamp(attrs.end || 0);
    if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
      return end - start;
    }
    return 1.8;
  }

  function normalizeCaptionCue(index, start, duration, text) {
    const safeStart = Number.isFinite(start) ? start : 0;
    const safeDuration = Number.isFinite(duration) ? duration : 1.8;
    return {
      id: String(index),
      start: safeStart,
      end: safeStart + Math.max(safeDuration, 0.8),
      text: normalizeCaptionText(text)
    };
  }

  function readCaptionNodes(xmlText, tagName) {
    const nodes = [];
    const pattern = new RegExp(`<${tagName}\\b([^>]*)>([\\s\\S]*?)<\\/${tagName}>`, "gi");
    let match = pattern.exec(xmlText || "");
    while (match) {
      nodes.push({
        attrs: readAttributes(match[1] || ""),
        body: decodeXmlEntities(match[2] || "")
      });
      match = pattern.exec(xmlText || "");
    }
    return nodes;
  }

  function stripCaptionMarkup(text) {
    return decodeXmlEntities(String(text || "").replace(/<[^>]+>/g, ""));
  }

  function parseVttCaptions(vttText) {
    return String(vttText || "")
      .replace(/\r/g, "")
      .split(/\n{2,}/)
      .map((block, index) => {
        const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
        const timeIndex = lines.findIndex((line) => line.includes("-->"));
        if (timeIndex < 0) {
          return null;
        }

        const [startText, endText] = lines[timeIndex].split("-->").map((part) => part.trim().split(/\s+/)[0]);
        const start = parseTimedTextTimestamp(startText);
        const end = parseTimedTextTimestamp(endText);
        const text = stripCaptionMarkup(lines.slice(timeIndex + 1).join(" "));
        if (!Number.isFinite(start) || !Number.isFinite(end) || !text) {
          return null;
        }
        return {
          id: String(index),
          start,
          end: Math.max(end, start + 0.8),
          text: normalizeCaptionText(text)
        };
      })
      .filter(Boolean);
  }

  function parseTimedTextTimestamp(value) {
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : NaN;
    }

    const input = String(value || "").trim();
    if (!input) {
      return NaN;
    }

    if (/^\d+(\.\d+)?s?$/.test(input)) {
      return Number(input.replace(/s$/, ""));
    }

    const parts = input.split(":");
    if (parts.length >= 2 && parts.length <= 3) {
      const seconds = Number(parts.pop().replace(",", "."));
      const minutes = Number(parts.pop());
      const hours = parts.length ? Number(parts.pop()) : 0;
      if ([seconds, minutes, hours].every(Number.isFinite)) {
        return hours * 3600 + minutes * 60 + seconds;
      }
    }

    return NaN;
  }

  function stripJsonProtectionPrefix(value) {
    return String(value || "").replace(/^\)\]\}'\s*\n?/, "").trim();
  }

  function normalizeCaptionText(text) {
    return decodeXmlEntities(String(text || ""))
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeRollingCaptionCues(cues, options = {}) {
    const list = (Array.isArray(cues) ? cues : [])
      .filter(Boolean)
      .slice()
      .sort((left, right) => Number(left.start || 0) - Number(right.start || 0) || Number(left.end || 0) - Number(right.end || 0));
    const maxGap = clampNumber(options.maxGap, 0, 1, 0.16);
    const result = [];
    let previousSnapshot = "";
    let previousCue = null;
    let lastOutputEnd = 0;

    for (const cue of list) {
      const start = Math.max(0, Number(cue.start || 0));
      const end = Math.max(start + 0.2, Number(cue.end || start + 1));
      const hasTranslatedText = Boolean(normalizeCaptionText(cue.translatedText || ""));
      const snapshot = stripNonSpeechCaptionText(normalizeCaptionText(
        hasTranslatedText ? cue.translatedText : cue.text
      ));
      const closeToPrevious = previousCue && start <= Number(previousCue.end || 0) + maxGap;
      const novel = closeToPrevious ? extractNovelCaptionText(previousSnapshot, snapshot) : { text: snapshot, consumed: 0 };

      if (novel.text) {
        const adjustedStart = Math.min(end - 0.18, Math.max(start, lastOutputEnd));
        const normalizedCue = {
          ...cue,
          start: Math.max(start, adjustedStart),
          end
        };
        if (hasTranslatedText) {
          normalizedCue.translatedText = novel.text;
        } else {
          normalizedCue.text = novel.text;
        }
        result.push(normalizedCue);
        lastOutputEnd = end;
      }

      if (snapshot) {
        previousSnapshot = snapshot;
      }
      previousCue = { start, end };
    }

    return result;
  }

  function stripNonSpeechCaptionText(text) {
    return String(text || "")
      .replace(/\[(?:music|音乐|applause|掌声|laughter|笑声|noise|噪音)[^\]]*\]/gi, " ")
      .replace(/[（(](?:music|音乐|applause|掌声|laughter|笑声|noise|噪音)[^）)]*[）)]/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function extractNovelCaptionText(previousText, currentText) {
    const previous = String(previousText || "").trim();
    const current = String(currentText || "").trim();
    if (!current) {
      return { text: "", consumed: 0 };
    }
    if (!previous) {
      return { text: current, consumed: 0 };
    }
    if (current === previous || previous.endsWith(current)) {
      return { text: "", consumed: current.length };
    }
    if (current.startsWith(previous)) {
      return { text: current.slice(previous.length).trim(), consumed: previous.length };
    }

    const containsCjk = /[\u3400-\u9fff]/.test(`${previous}${current}`);
    const minOverlap = containsCjk ? 2 : 4;
    const maxOverlap = Math.min(previous.length, current.length);
    for (let overlap = maxOverlap; overlap >= minOverlap; overlap -= 1) {
      if (previous.slice(-overlap) === current.slice(0, overlap)) {
        return { text: current.slice(overlap).trim(), consumed: overlap };
      }
    }
    return { text: current, consumed: 0 };
  }

  function makePlaybackTranslationBatches(cues, currentTime, options = {}) {
    const list = Array.isArray(cues) ? cues.filter(Boolean) : [];
    if (!list.length) {
      return [];
    }

    const firstBatchSize = clampInteger(options.firstBatchSize, 1, 48, 18);
    const batchSize = clampInteger(options.batchSize, 1, 64, 24);
    const pivotTime = Number.isFinite(Number(currentTime)) ? Number(currentTime) : 0;
    const startIndex = findCueIndexAtOrAfter(list, pivotTime);
    const forward = list.slice(startIndex);
    const backward = list.slice(0, startIndex);
    const batches = [];

    if (forward.length) {
      batches.push(forward.slice(0, firstBatchSize));
      pushChunks(batches, forward.slice(firstBatchSize), batchSize);
    }
    pushChunks(batches, backward, batchSize);
    return batches.filter((batch) => batch.length);
  }

  function cueKey(cue) {
    return [cue?.id || "", Number(cue?.start || 0).toFixed(3), Number(cue?.end || 0).toFixed(3), cue?.text || ""].join("|");
  }

  function buildSemanticVoiceSegments(cues, options = {}) {
    const list = (Array.isArray(cues) ? cues : []).filter(
      (cue) => cue && String(cue.translatedText || cue.text || "").trim()
    );
    const language = String(options.language || "").toLowerCase();
    const minDuration = clampNumber(options.minDuration, 0.2, 3, 0.85);
    const maxDuration = clampNumber(options.maxDuration, minDuration, 12, 4.2);
    const maxGap = clampNumber(options.maxGap, 0, 2, 0.18);
    const maxCues = clampInteger(options.maxCues, 1, 12, 3);
    const maxChars = clampInteger(options.maxChars, 8, 400, 72);
    const silenceSlack = clampNumber(options.silenceSlack, 0, 3, 0.65);
    const compactLanguage = /^(zh|ja|ko)/.test(language);

    const cueText = (cue) => String(cue?.translatedText || cue?.text || "").trim();
    const groupDuration = (group) =>
      group.length ? Number(group[group.length - 1].end || 0) - Number(group[0].start || 0) : 0;
    const sentenceComplete = (group) => /[。！？.!?]$/.test(cueText(group[group.length - 1]));
    const joinText = (group) => {
      const merged = group.reduce((result, nextCue, cueIndex) => {
        const nextText = cueText(nextCue);
        if (!nextText) {
          return result;
        }
        if (!result) {
          return nextText;
        }
        if (result.endsWith(nextText)) {
          return result;
        }
        if (nextText.startsWith(result)) {
          return nextText;
        }
        const minOverlap = compactLanguage ? 2 : 4;
        const maxOverlap = Math.min(result.length, nextText.length);
        for (let overlap = maxOverlap; overlap >= minOverlap; overlap -= 1) {
          if (result.slice(-overlap) === nextText.slice(0, overlap)) {
            return result + nextText.slice(overlap);
          }
        }
        const previousCue = group[cueIndex - 1];
        const gap = previousCue
          ? Number(nextCue.start || 0) - Number(previousCue.end || 0)
          : 0;
        const hasPunctuationBoundary = /[，。！？；：、,.!?;:]$/.test(result) || /^[，。！？；：、,.!?;:]/.test(nextText);
        const separator = compactLanguage
          ? gap >= 0.16 && !hasPunctuationBoundary
            ? "，"
            : ""
          : " ";
        return `${result}${separator}${nextText}`;
      }, "");
      return merged
        .replace(/\s*([，。！？；：、,.!?;:])\s*/g, "$1")
        .replace(/([，、])([。！？,.!?])/g, "$2")
        .replace(/([。！？.!?])，/g, "$1")
        .trim();
    };
    const canMerge = (group, nextCue) => {
      if (!group.length || group.length >= maxCues) {
        return false;
      }
      const currentDuration = groupDuration(group);
      if (sentenceComplete(group) && currentDuration >= minDuration) {
        return false;
      }
      const first = group[0];
      const previous = group[group.length - 1];
      const gap = Number(nextCue.start || 0) - Number(previous.end || 0);
      if (gap > maxGap) {
        return false;
      }
      const projectedDuration = Number(nextCue.end || 0) - Number(first.start || 0);
      if (projectedDuration > maxDuration || joinText([...group, nextCue]).length > maxChars) {
        return false;
      }
      return true;
    };

    const segments = [];
    let cueIndex = 0;
    while (cueIndex < list.length) {
      const startCueIndex = cueIndex;
      const group = [list[cueIndex]];
      cueIndex += 1;
      while (cueIndex < list.length && canMerge(group, list[cueIndex])) {
        group.push(list[cueIndex]);
        cueIndex += 1;
        if (sentenceComplete(group) && groupDuration(group) >= minDuration) {
          break;
        }
      }

      const first = group[0];
      const last = group[group.length - 1];
      const start = Number(first.start || 0);
      const end = Math.max(Number(last.end || start + 1), start + 0.45);
      segments.push({
        id: `voice-${segments.length}-${start.toFixed(3)}`,
        key: group.map(cueKey).join("~"),
        start,
        end,
        duration: end - start,
        text: joinText(group),
        cueKeys: group.map(cueKey),
        startCueIndex,
        endCueIndex: startCueIndex + group.length - 1
      });
    }

    return segments.map((segment, index) => {
      const nextStart = Number(segments[index + 1]?.start);
      const naturalEnd = Number(segment.end || segment.start + 0.45);
      const hasNextStart = Number.isFinite(nextStart) && nextStart > naturalEnd;
      const slackEnd = hasNextStart ? Math.min(naturalEnd + silenceSlack, nextStart - 0.03) : naturalEnd;
      const timeboxEnd = Math.max(naturalEnd, slackEnd, Number(segment.start || 0) + 0.45);
      return {
        ...segment,
        timeboxEnd,
        timeboxDuration: timeboxEnd - Number(segment.start || 0)
      };
    });
  }

  function extendSemanticVoiceSegments(existingSegments, cues, options = {}) {
    const existing = Array.isArray(existingSegments) ? existingSegments.filter(Boolean) : [];
    const coveredCueKeys = new Set(existing.flatMap((segment) => segment.cueKeys || []));
    const uncoveredCues = (Array.isArray(cues) ? cues : []).filter((cue) => !coveredCueKeys.has(cueKey(cue)));
    return [...existing, ...buildSemanticVoiceSegments(uncoveredCues, options)].sort(
      (left, right) => Number(left.start || 0) - Number(right.start || 0)
    );
  }

  function resolveVoiceCaptionText(cue, voiceSegments, voiceEnabled = true) {
    const fallback = String(cue?.translatedText || cue?.text || "").trim();
    if (!voiceEnabled || !cue) {
      return fallback;
    }
    const key = cueKey(cue);
    const segment = (Array.isArray(voiceSegments) ? voiceSegments : []).find(
      (candidate) => Array.isArray(candidate?.cueKeys) && candidate.cueKeys.includes(key)
    );
    return String(segment?.text || fallback).trim();
  }

  function computeVoiceSynthesisDuration(segment) {
    const start = Math.max(0, Number(segment?.start || 0));
    const end = Math.max(start + 0.35, Number(segment?.end || start + 0.35));
    return end - start;
  }

  function captionEngineWaitTimeout(pageResult, pageFallbackMs = 2000, totalMs = 23000) {
    const fallback = clampInteger(pageFallbackMs, 100, 30000, 2000);
    const total = clampInteger(totalMs, fallback, 120000, 23000);
    return pageResult?.status === "captions" && Array.isArray(pageResult.cues) && pageResult.cues.length
      ? fallback
      : total;
  }

  function createCueTranslationTracker(isTranslated) {
    const pendingKeys = new Set();

    function isPending(cue) {
      return pendingKeys.has(cueKey(cue));
    }

    function reserve(cues) {
      const next = [];
      for (const cue of Array.isArray(cues) ? cues : []) {
        if ((typeof isTranslated === "function" && isTranslated(cue)) || isPending(cue)) {
          continue;
        }
        pendingKeys.add(cueKey(cue));
        next.push(cue);
      }
      return next;
    }

    function release(cues) {
      for (const cue of Array.isArray(cues) ? cues : []) {
        pendingKeys.delete(cueKey(cue));
      }
    }

    function clear() {
      pendingKeys.clear();
    }

    function size() {
      return pendingKeys.size;
    }

    return {
      clear,
      isPending,
      release,
      reserve,
      size
    };
  }

  function readAttributes(source) {
    const attrs = {};
    const attrPattern = /([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
    let match = attrPattern.exec(source);
    while (match) {
      attrs[match[1]] = decodeXmlEntities(match[2] ?? match[3] ?? "");
      match = attrPattern.exec(source);
    }
    return attrs;
  }

  function decodeXmlEntities(value) {
    let decoded = String(value || "");
    for (let index = 0; index < 3; index += 1) {
      const next = decoded
        .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
        .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)))
        .replace(/&quot;/g, "\"")
        .replace(/&apos;/g, "'")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
      if (next === decoded) {
        return decoded;
      }
      decoded = next;
    }
    return decoded;
  }

  function extractBalancedJson(source, startIndex) {
    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let index = startIndex; index < source.length; index += 1) {
      const char = source[index];

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === "\"") {
          inString = false;
        }
        continue;
      }

      if (char === "\"") {
        inString = true;
      } else if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          return source.slice(startIndex, index + 1);
        }
      }
    }

    return "";
  }

  function findCueIndexAtOrAfter(cues, currentTime) {
    const tolerance = 0.35;
    const index = cues.findIndex((cue) => Number(cue.end ?? cue.start ?? 0) >= currentTime - tolerance);
    if (index >= 0) {
      return index;
    }
    return Math.max(0, cues.length - 1);
  }

  function pushChunks(target, cues, batchSize) {
    for (let index = 0; index < cues.length; index += batchSize) {
      target.push(cues.slice(index, index + batchSize));
    }
  }

  function clampInteger(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return fallback;
    }
    return Math.min(max, Math.max(min, Math.round(number)));
  }

  function computeAudioMixState(settings = {}, context = {}) {
    const originalVolume = clampNumber(settings.originalVolume, 0, 1, 0.25);
    const voiceEnabled = Boolean(settings.voiceEnabled);
    return {
      shouldApply: Boolean(context.mutedByLocalTube),
      shouldCancelSpeech: !voiceEnabled,
      muted: Boolean(settings.muteOriginal),
      volume: originalVolume,
      shouldSpeakCurrentCue:
        Boolean(context.running) &&
        voiceEnabled &&
        Number(context.activeCueIndex) >= 0 &&
        Number(context.activeCueIndex) !== Number(context.spokenCueIndex)
    };
  }

  function computeFullTrackSync(videoTime, audioTime, videoRate, options = {}) {
    const desiredTime = Math.max(0, Number(videoTime) || 0);
    const currentAudioTime = Math.max(0, Number(audioTime) || 0);
    const baseRate = clampNumber(videoRate, 0.25, 4, 1);
    const drift = currentAudioTime - desiredTime;
    const seekThreshold = clampNumber(options.seekThreshold, 0.08, 2, 0.18);
    if (Math.abs(drift) > seekThreshold) {
      return {
        drift,
        seekTo: desiredTime,
        playbackRate: baseRate
      };
    }

    const correction = clampNumber(1 - drift * 0.35, 0.97, 1.03, 1);
    return {
      drift,
      seekTo: null,
      playbackRate: clampNumber(baseRate * correction, 0.25, 4, baseRate)
    };
  }

  function computeVoiceRateBudget(segment, ttsEngine, preparedFitRate = 1) {
    const duration = Math.max(0, Number(segment?.duration || 0));
    const naturalOnline = String(ttsEngine || "").toLowerCase() === "edge";
    let comfortTotalRate;
    let deadlineTotalRate;

    if (naturalOnline) {
      if (duration <= 2.2) {
        comfortTotalRate = 1.22;
        deadlineTotalRate = 1.4;
      } else if (duration <= 3.5) {
        comfortTotalRate = 1.16;
        deadlineTotalRate = 1.34;
      } else {
        comfortTotalRate = 1.12;
        deadlineTotalRate = 1.3;
      }
    } else if (duration <= 1.8) {
      comfortTotalRate = 1.3;
      deadlineTotalRate = 1.4;
    } else if (duration <= 2.8) {
      comfortTotalRate = 1.25;
      deadlineTotalRate = 1.36;
    } else {
      comfortTotalRate = 1.2;
      deadlineTotalRate = 1.32;
    }

    const preparedRate = clampNumber(preparedFitRate, 1, 3, 1);
    return {
      comfortTotalRate,
      deadlineTotalRate,
      liveMaxRateMultiplier: Math.max(1, deadlineTotalRate / preparedRate)
    };
  }

  function computeVoiceSyncTiming(ttsEngine) {
    const naturalOnline = String(ttsEngine || "").toLowerCase() === "edge";
    return naturalOnline
      ? { startEarly: 0.12, finishGuard: 0.14 }
      : { startEarly: 0.08, finishGuard: 0.06 };
  }

  function computeLiveVoiceSync(videoTime, videoRate, audioTime, audioDuration, segment, options = {}) {
    const start = Math.max(0, Number(segment?.start || 0));
    const targetEnd = Math.max(start + 0.2, Number(segment?.end || start + 0.2));
    const hardEnd = Math.max(targetEnd, Number(segment?.timeboxEnd || targetEnd));
    const now = Math.max(0, Number(videoTime) || 0);
    const rate = clampNumber(videoRate, 0.25, 4, 1);
    const duration = Math.max(0, Number(audioDuration) || 0);
    const currentAudioTime = clampNumber(audioTime, 0, duration || Infinity, 0);
    const endGrace = clampNumber(options.endGrace, 0, 0.5, 0.04);
    const finishGuard = clampNumber(options.finishGuard, 0, 0.25, 0.06);
    const startEarly = clampNumber(options.startEarly, 0, 0.3, 0.08);
    const seekGrace = clampNumber(options.seekGrace, 0, 2, 0.42);
    const seekThreshold = clampNumber(options.seekThreshold, 0.05, 3, 0.55);
    const minRate = Math.max(0.25, rate);
    const maxRateMultiplier = clampNumber(options.maxRateMultiplier, 1, 2, 1.45);
    const maxRate = Math.max(minRate, rate * maxRateMultiplier);

    if (now >= hardEnd + endGrace || duration <= 0.05) {
      return {
        action: "stop",
        playbackRate: minRate,
        plannedRate: minRate,
        requiredRate: minRate,
        seekTo: null,
        expectedEnd: now,
        lateRisk: false
      };
    }

    const segmentDuration = Math.max(0.2, targetEnd - start);
    const progress = clampNumber((now - start) / segmentDuration, 0, 1, 0);
    const desiredAudioTime = Math.min(Math.max(0, duration - 0.08), progress * duration);
    const shouldSeek =
      Boolean(options.explicitSeek) &&
      now > start + seekGrace &&
      Math.abs(currentAudioTime - desiredAudioTime) > seekThreshold;
    const alignedAudioTime = shouldSeek ? desiredAudioTime : currentAudioTime;
    const remainingAudio = Math.max(0.01, duration - alignedAudioTime);
    const remainingTargetVideo = Math.max(0.06, targetEnd - now - finishGuard);
    const remainingHardVideo = Math.max(0.06, hardEnd - now - finishGuard);
    const requiredRate = (remainingAudio * rate) / remainingTargetVideo;
    const hardBoundaryRate = (remainingAudio * rate) / remainingHardVideo;
    const requestedPlannedRate = Number(options.plannedRate);
    const hasPlannedRate = Number.isFinite(requestedPlannedRate) && requestedPlannedRate > 0;
    const plannedRate = hasPlannedRate
      ? clampNumber(requestedPlannedRate, minRate, maxRate, minRate)
      : requiredRate <= maxRate
        ? clampNumber(requiredRate, minRate, maxRate, minRate)
        : clampNumber(hardBoundaryRate, minRate, maxRate, maxRate);
    const anchorVideoTime = Number(options.anchorVideoTime);
    const anchorAudioTime = Number(options.anchorAudioTime);
    let playbackRate = plannedRate;
    if (hasPlannedRate && Number.isFinite(anchorVideoTime) && Number.isFinite(anchorAudioTime)) {
      const expectedAudioTime = clampNumber(
        anchorAudioTime + (Math.max(0, now - anchorVideoTime) * plannedRate) / rate,
        0,
        duration,
        currentAudioTime
      );
      const drift = currentAudioTime - expectedAudioTime;
      const correction = clampNumber(1 - drift * 0.18, 0.97, 1.03, 1);
      playbackRate = clampNumber(plannedRate * correction, minRate, maxRate, plannedRate);
    }
    const expectedEnd = now + (remainingAudio / playbackRate) * rate;
    let action = "none";
    if (Boolean(options.videoPaused) || Boolean(options.videoSeeking) || Boolean(options.buffering) || now < start - startEarly) {
      action = "pause";
    } else if (Boolean(options.audioPaused)) {
      action = "play";
    }

    return {
      action,
      playbackRate,
      plannedRate,
      requiredRate,
      seekTo: shouldSeek ? desiredAudioTime : null,
      expectedEnd,
      lateRisk: hardBoundaryRate > maxRate + 0.01,
      targetEnd,
      hardEnd
    };
  }

  function syncLiveVoiceMediaElements(video, audio, segment, options = {}) {
    if (!video || !audio || !segment) {
      return {
        active: false,
        action: "none",
        playbackRate: 1,
        requiredRate: 1,
        seekTo: null,
        expectedEnd: 0,
        lateRisk: false
      };
    }
    const sync = computeLiveVoiceSync(
      video.currentTime,
      video.playbackRate,
      audio.currentTime,
      audio.duration,
      segment,
      {
        ...options,
        videoPaused: video.paused,
        videoSeeking: video.seeking,
        audioPaused: audio.paused
      }
    );
    if (sync.seekTo !== null) {
      try {
        audio.currentTime = sync.seekTo;
      } catch (error) {
        // A media element can reject seeks until metadata is available.
      }
    }
    audio.playbackRate = sync.playbackRate;
    if ((sync.action === "pause" || sync.action === "stop") && !audio.paused && typeof audio.pause === "function") {
      audio.pause();
    }
    return { active: true, ...sync };
  }

  function syncFullTrackMediaElements(video, audio, options = {}) {
    if (!video || !audio) {
      return { active: false, action: "none", drift: 0, seekTo: null, playbackRate: 1 };
    }
    const originalVolume = clampNumber(options.originalVolume, 0, 1, 0.25);
    video.muted = Boolean(options.mixOriginal) || Boolean(options.muteOriginal);
    video.volume = originalVolume;

    const sync = computeFullTrackSync(video.currentTime, audio.currentTime, video.playbackRate, {
      seekThreshold: options.seekThreshold
    });
    if (options.forceSeek || sync.seekTo !== null) {
      const duration = Number(audio.duration);
      const maxTime = Number.isFinite(duration) && duration > 0 ? duration : Infinity;
      const target = clampNumber(sync.seekTo === null ? video.currentTime : sync.seekTo, 0, maxTime, 0);
      try {
        audio.currentTime = target;
      } catch (error) {
        // A media element can reject seeks until metadata is available.
      }
    }
    audio.playbackRate = sync.playbackRate;

    if (video.ended || audio.ended) {
      if (!audio.paused && typeof audio.pause === "function") {
        audio.pause();
      }
      return { active: true, action: "stop", ...sync };
    }
    if (video.paused || video.seeking || options.buffering) {
      if (!audio.paused && typeof audio.pause === "function") {
        audio.pause();
      }
      return { active: true, action: "pause", ...sync };
    }
    if (audio.paused && Number(audio.readyState || 0) >= 2) {
      return { active: true, action: "play", ...sync };
    }
    return { active: true, action: "none", ...sync };
  }

  function clampNumber(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return fallback;
    }
    return Math.min(max, Math.max(min, number));
  }

  function selectNewRollingCues(existingCues, incomingCues, previousCoverageEnd, overlapSeconds = 1.2) {
    const coverageEnd = Number(previousCoverageEnd || 0);
    const overlap = clampNumber(overlapSeconds, 0, 10, 1.2);
    const recent = (Array.isArray(existingCues) ? existingCues : []).filter(
      (cue) => Number(cue?.end || 0) >= coverageEnd - 4
    );
    return (Array.isArray(incomingCues) ? incomingCues : [])
      .filter((cue) => Number(cue?.end || 0) > coverageEnd - 0.05)
      .filter((cue) => {
        const text = normalizeRollingCueText(cue?.text);
        return !recent.some(
          (existing) =>
            normalizeRollingCueText(existing?.text) === text &&
            Math.abs(Number(existing?.start || 0) - Number(cue?.start || 0)) <= overlap + 0.8
        );
      })
      .map((cue) => ({
        ...cue,
        start: Math.max(Number(cue?.start || 0), coverageEnd - 0.05),
        end: Math.max(Number(cue?.end || 0), coverageEnd + 0.45)
      }));
  }

  function normalizeRollingCueText(text) {
    return String(text || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "").trim();
  }

  function mergeCueTimeline(existingCues, nextCues) {
    const byKey = new Map();
    for (const cue of [...(existingCues || []), ...(nextCues || [])]) {
      byKey.set(cueKey(cue), cue);
    }
    return Array.from(byKey.values()).sort((a, b) => Number(a?.start || 0) - Number(b?.start || 0));
  }

  function normalizeExportCues(cues) {
    return (Array.isArray(cues) ? cues : [])
      .map((cue) => {
        const text = String(cue?.translatedText || cue?.text || "")
          .replace(/\r\n?/g, "\n")
          .replace(/\u0000/g, "")
          .trim();
        const rawStart = Number(cue?.start || 0);
        const start = Number.isFinite(rawStart) ? Math.max(0, rawStart) : 0;
        const rawEnd = Number(cue?.end);
        const end = Number.isFinite(rawEnd) ? Math.max(start + 0.05, rawEnd) : start + 2;
        return { start, end, text };
      })
      .filter((cue) => cue.text)
      .sort((a, b) => a.start - b.start || a.end - b.end);
  }

  function formatSubtitleTimestamp(seconds, separator) {
    const totalMilliseconds = Math.max(0, Math.round(Number(seconds || 0) * 1000));
    const hours = Math.floor(totalMilliseconds / 3600000);
    const minutes = Math.floor((totalMilliseconds % 3600000) / 60000);
    const wholeSeconds = Math.floor((totalMilliseconds % 60000) / 1000);
    const milliseconds = totalMilliseconds % 1000;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}${separator}${String(milliseconds).padStart(3, "0")}`;
  }

  function serializeSubtitleCues(cues, format = "srt") {
    const normalized = normalizeExportCues(cues);
    if (!normalized.length) {
      return "";
    }
    const normalizedFormat = String(format || "srt").toLowerCase() === "vtt" ? "vtt" : "srt";
    const separator = normalizedFormat === "vtt" ? "." : ",";
    const blocks = normalized.map(
      (cue, index) =>
        `${index + 1}\n${formatSubtitleTimestamp(cue.start, separator)} --> ${formatSubtitleTimestamp(cue.end, separator)}\n${cue.text}`
    );
    const body = `${blocks.join("\n\n")}\n`;
    return normalizedFormat === "vtt" ? `WEBVTT\n\n${body}` : body;
  }

  function makeDubTrackRenderCues(voiceSegments, fallbackCues) {
    const segments = (Array.isArray(voiceSegments) ? voiceSegments : [])
      .map((segment) => ({
        start: Number(segment?.start || 0),
        end: Math.max(
          Number(segment?.timeboxEnd || segment?.end || 0),
          Number(segment?.end || segment?.start || 0)
        ),
        text: String(segment?.text || "").trim()
      }))
      .filter((segment) => segment.text);
    return normalizeExportCues(segments.length ? segments : fallbackCues);
  }

  function makeTimelineCacheLookupRequests(request = {}) {
    const selected = {
      videoId: String(request.videoId || ""),
      targetLanguage: String(request.targetLanguage || ""),
      provider: String(request.provider || ""),
      model: String(request.model || "")
    };
    const youtubeCaptions = {
      ...selected,
      provider: "youtube-captions",
      model: ""
    };
    return selected.provider === youtubeCaptions.provider
      ? [youtubeCaptions]
      : [youtubeCaptions, selected];
  }

  function makeInnertubePlayerRequest(config = {}, videoId = "") {
    const apiKey = String(config?.apiKey || "").trim();
    const safeVideoId = String(videoId || "").trim();
    const sourceClient = config?.context?.client && typeof config.context.client === "object"
      ? config.context.client
      : {};
    const clientVersion = String(config?.clientVersion || sourceClient.clientVersion || "").trim();
    if (!apiKey || !safeVideoId || !clientVersion) {
      return null;
    }
    const client = {
      clientName: String(sourceClient.clientName || config?.clientName || "WEB"),
      clientVersion
    };
    for (const key of ["hl", "gl", "visitorData", "userAgent", "utcOffsetMinutes"]) {
      if (sourceClient[key] !== undefined && sourceClient[key] !== null && sourceClient[key] !== "") {
        client[key] = sourceClient[key];
      }
    }
    const clientNameId = Math.max(1, Number(config?.clientNameId || 1) || 1);
    return {
      url: `https://www.youtube.com/youtubei/v1/player?key=${encodeURIComponent(apiKey)}&prettyPrint=false`,
      headers: {
        "content-type": "application/json",
        "x-youtube-client-name": String(clientNameId),
        "x-youtube-client-version": clientVersion
      },
      body: JSON.stringify({
        context: { client },
        videoId: safeVideoId,
        contentCheckOk: true,
        racyCheckOk: true
      })
    };
  }

  function normalizeLanguagePrefix(language) {
    const value = String(language || "").trim().toLowerCase();
    if (!value || value === "auto") {
      return "";
    }
    return value.split(/[-_]/)[0] || "";
  }

  function normalizeCaptionLanguage(language) {
    const value = String(language || "").trim().toLowerCase().replace(/_/g, "-");
    if (!value || value === "auto") {
      return "";
    }
    if (["zh-cn", "zh-hans", "zh-chs"].some((alias) => value === alias || value.startsWith(`${alias}-`))) {
      return "zh-hans";
    }
    if (["zh-tw", "zh-hant", "zh-cht", "zh-hk", "zh-mo"].some((alias) => value === alias || value.startsWith(`${alias}-`))) {
      return "zh-hant";
    }
    if (value === "pt-br" || value.startsWith("pt-br-")) {
      return "pt-br";
    }
    return value.split("-")[0] || "";
  }

  const api = {
    addQuery,
    buildSemanticVoiceSegments,
    captionEngineWaitTimeout,
    computeAudioMixState,
    computeFullTrackSync,
    computeVoiceRateBudget,
    computeVoiceSynthesisDuration,
    computeVoiceSyncTiming,
    computeLiveVoiceSync,
    syncFullTrackMediaElements,
    syncLiveVoiceMediaElements,
    createCueTranslationTracker,
    cueKey,
    extractBalancedJson,
    extendSemanticVoiceSegments,
    limitCaptionTrackAttempts,
    makeCaptionFetchCandidates,
    makeInnertubePlayerRequest,
    makePlaybackTranslationBatches,
    makeTimelineCacheLookupRequests,
    mergeCueTimeline,
    normalizeCaptionLanguage,
    makeDubTrackRenderCues,
    normalizeExportCues,
    normalizeRollingCaptionCues,
    parseCaptionPayload,
    pickCaptionTrack,
    responseMatchesVideo,
    resolveVoiceCaptionText,
    selectNewRollingCues,
    serializeSubtitleCues
  };

  globalScope.LocalTubeDubHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
