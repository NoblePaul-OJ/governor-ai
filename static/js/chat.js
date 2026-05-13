const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const typingIndicator = document.getElementById("typing-indicator");
const emptyState = document.getElementById("empty-state");
const STORAGE_KEY = "governor_user";
const SESSION_KEY = "governor_session_id";

let userProfile = null;
let lastUserMessage = "";
let responseCount = 0;
let profileReady = false;
let profileInitializationPromise = null;
let onboardingStep = 0;
let onboardingActive = false;
let initialGreetingMessage = null;
let onboardingDraft = {
  name: "",
  department: "",
  level: "",
};

function now() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function typeText(element, text, speed = 10) {
  let i = 0;
  element.textContent = "";

  function typing() {
    if (i < text.length) {
      element.textContent += text.charAt(i);
      i++;
      setTimeout(typing, speed);
    }
  }

  typing();
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizePhoneTarget(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const cleaned = raw.replace(/[^\d+]/g, "");
  return cleaned || raw;
}

function normalizeWhatsAppTarget(value) {
  const raw = String(value || "").trim();
  const digits = raw.replace(/[^\d]/g, "");
  if (!digits) return "";
  if (digits.startsWith("234")) return digits;
  if (digits.startsWith("0") && digits.length === 11) {
    return `234${digits.slice(1)}`;
  }
  return digits;
}

function normalizeContactList(value) {
  if (Array.isArray(value)) {
    const seen = new Set();
    return value
      .map((item) => cleanContactText(item))
      .filter((item) => {
        if (!item || seen.has(item)) return false;
        seen.add(item);
        return true;
      });
  }

  const single = cleanContactText(value);
  return single ? [single] : [];
}

function resolveContactValues(primary, fallback) {
  const primaryValues = normalizeContactList(primary);
  if (primaryValues.length) return primaryValues;
  return normalizeContactList(fallback);
}

function cleanContactText(value) {
  const text = String(value || "").trim();
  if (!text) return "";

  const normalized = normalizeText(text);
  const placeholders = new Set([
    "n a",
    "na",
    "none",
    "not available",
    "not available yet",
    "unavailable",
    "unavailable yet",
    "unknown",
  ]);

  if (placeholders.has(normalized)) {
    return "";
  }

  return text;
}

function normalizeEmailTarget(value) {
  const text = cleanContactText(value);
  if (!text) return "";
  return text.replace(/^mailto:/i, "").trim();
}

function isLikelyEmailAddress(value) {
  const email = normalizeEmailTarget(value);
  if (!email) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function formatNaturalList(items) {
  const list = normalizeContactList(items);
  if (!list.length) return "";
  if (list.length === 1) return list[0];
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.slice(0, -1).join(", ")}, and ${list[list.length - 1]}`;
}

function pickContactSummary(contact) {
  if (!contact || typeof contact !== "object") return "";

  const issues = normalizeContactList(contact.common_issues || contact.handles || contact.common_issue_types);
  if (issues.length) {
    return `${formatNaturalList(issues.slice(0, 4))}.`;
  }

  const directSummary = cleanContactText(contact.description || contact.note || "");
  if (directSummary) {
    const cleanedSummary = directSummary.replace(/^(handles?|provides?|supports?|manages?|offers?|covers?)\s+/i, "");
    return cleanedSummary || directSummary;
  }

  return "";
}

function isContactReply(text, contact) {
  if (contact && typeof contact === "object") return true;
  const normalized = normalizeText(text);
  return normalized.includes("contact details") || normalized.includes("phone") || normalized.includes("email");
}

function createContactAnchor(value, href, extraClass) {
  const link = document.createElement("a");
  link.className = `contact-link ${extraClass || ""}`.trim();
  link.href = href;
  link.textContent = value;
  if (/^https?:/i.test(href)) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return link;
}

function createLabeledContactRow(label, contentNode, rowClass = "") {
  const row = document.createElement("div");
  row.className = `contact-row ${rowClass}`.trim();

  const name = document.createElement("span");
  name.className = "contact-label";
  name.textContent = `${label}:`;

  row.appendChild(name);
  row.appendChild(contentNode);
  return row;
}

function createTextContactRow(label, value, rowClass = "") {
  if (!value) return null;

  const content = document.createElement("span");
  content.className = "contact-value";
  content.textContent = value;
  return createLabeledContactRow(label, content, rowClass);
}

function createLinkedContactRow(label, values, hrefFactory, extraClass, rowClass = "") {
  const items = normalizeContactList(values);
  if (!items.length) return null;

  const stack = document.createElement("div");
  stack.className = "contact-link-list";

  items.forEach((value) => {
    const href = hrefFactory(value);
    if (!href) return;
    stack.appendChild(createContactAnchor(value, href, extraClass));
  });

  if (!stack.children.length) return null;
  return createLabeledContactRow(label, stack, rowClass);
}

function renderContactCard(contact) {
  return renderCompactContactCard(contact);

  if (!contact || typeof contact !== "object") return null;

  const phoneValues = normalizeContactList(contact.phones || contact.phone);
  const emailValues = normalizeContactList(contact.emails || contact.email);
  const summary = pickContactSummary(contact);
  const office = cleanContactText(contact.office_location || contact.office || "");
  const officeHours = cleanContactText(contact.office_hours || "");
  const preferred = cleanContactText(contact.preferred_contact_method || "");
  const whatsapp = cleanContactText(contact.whatsapp || "");

  const hasVisibleDetails = phoneValues.length || emailValues.length || whatsapp || office || officeHours || preferred || summary;
  if (!hasVisibleDetails) {
    return null;
  }

  const card = document.createElement("article");
  card.className = "contact-card";

  const title = document.createElement("div");
  title.className = "contact-card-title";
  title.textContent = contact.unit_name || contact.office_name || "Contact";
  card.appendChild(title);

  const actions = document.createElement("div");
  actions.className = "contact-card-actions";
  const seenActions = new Set();

  phoneValues.forEach((value) => {
    const href = `tel:${normalizePhoneTarget(value)}`;
    const key = href.toLowerCase();
    if (!normalizePhoneTarget(value) || seenActions.has(key)) return;
    seenActions.add(key);
    actions.appendChild(createContactAnchor(value, href, "phone contact-action"));
  });

  emailValues.forEach((value) => {
    if (!value) return;
    const href = `mailto:${value}`;
    const key = href.toLowerCase();
    if (seenActions.has(key)) return;
    seenActions.add(key);
    actions.appendChild(createContactAnchor(value, href, "email contact-action"));
  });

  if (whatsapp) {
    const waTarget = normalizeWhatsAppTarget(whatsapp);
    const waHref = waTarget ? `https://wa.me/${waTarget}` : `tel:${normalizePhoneTarget(whatsapp)}`;
    const key = waHref.toLowerCase();
    if (waHref && !seenActions.has(key)) {
      seenActions.add(key);
      actions.appendChild(createContactAnchor(whatsapp, waHref, "whatsapp contact-action"));
    }
  }

  if (actions.children.length) {
    card.appendChild(actions);
  }

  const meta = document.createElement("div");
  meta.className = "contact-card-meta";

  if (office) {
    const officeRow = document.createElement("div");
    officeRow.className = "contact-meta-item";
    officeRow.innerHTML = '<span class="contact-meta-icon">📍</span>';
    const officeText = document.createElement("span");
    officeText.textContent = office;
    officeRow.appendChild(officeText);
    meta.appendChild(officeRow);
  }

  if (officeHours) {
    const hoursRow = document.createElement("div");
    hoursRow.className = "contact-meta-item";
    hoursRow.innerHTML = '<span class="contact-meta-icon">🕒</span>';
    const hoursText = document.createElement("span");
    hoursText.textContent = officeHours;
    hoursRow.appendChild(hoursText);
    meta.appendChild(hoursRow);
  }

  if (preferred) {
    const preferredRow = document.createElement("div");
    preferredRow.className = "contact-meta-item";
    preferredRow.innerHTML = '<span class="contact-meta-icon">✨</span>';
    const preferredText = document.createElement("span");
    preferredText.textContent = preferred;
    preferredRow.appendChild(preferredText);
    meta.appendChild(preferredRow);
  }

  if (meta.children.length) {
    card.appendChild(meta);
  }

  if (summary) {
    const description = document.createElement("p");
    description.className = "contact-card-summary";
    description.textContent = summary;
    card.appendChild(description);
  }

  return card;
}

function createContactBadge(text, extraClass = "") {
  const badge = document.createElement("span");
  badge.className = `contact-badge ${extraClass}`.trim();
  badge.textContent = text;
  return badge;
}

function createContactValueGroup(values, hrefFactory, linkClass) {
  const items = normalizeContactList(values);
  if (!items.length) return null;

  const group = document.createElement("div");
  group.className = "contact-value-group";

  items.forEach((value) => {
    const href = hrefFactory ? hrefFactory(value) : "";
    if (href) {
      group.appendChild(createContactAnchor(value, href, linkClass));
      return;
    }

    const textNode = document.createElement("span");
    textNode.className = "contact-value-text";
    textNode.textContent = value;
    group.appendChild(textNode);
  });

  return group.children.length ? group : null;
}

function createContactDetailRow(iconText, labelText, valueNode, rowClass = "") {
  const row = document.createElement("div");
  row.className = `contact-detail-row ${rowClass}`.trim();

  const label = document.createElement("div");
  label.className = "contact-detail-label";

  if (iconText) {
    const icon = document.createElement("span");
    icon.className = "contact-detail-icon";
    icon.textContent = iconText;
    label.appendChild(icon);
  }

  const text = document.createElement("span");
  text.className = "contact-detail-label-text";
  text.textContent = labelText;
  label.appendChild(text);

  row.appendChild(label);
  row.appendChild(valueNode);
  return row;
}

function createPlainContactValue(value) {
  const text = document.createElement("span");
  text.className = "contact-value-text";
  text.textContent = value;
  return text;
}

function renderCompactContactCard(contact) {
  if (!contact || typeof contact !== "object") return null;

  const phoneValues = resolveContactValues(contact.phones, contact.phone);
  const emailValues = resolveContactValues(contact.emails, contact.email);
  const summary = pickContactSummary(contact);
  const office = cleanContactText(contact.office_location || contact.office || "");
  const officeHours = cleanContactText(contact.office_hours || "");
  const preferred = normalizeText(contact.preferred_contact_method || "");
  const supportsWhatsApp = Boolean(cleanContactText(contact.whatsapp || "")) || preferred.includes("whatsapp");

  const hasVisibleDetails = phoneValues.length || emailValues.length || office || officeHours || summary;
  if (!hasVisibleDetails) {
    return null;
  }

  const card = document.createElement("article");
  card.className = "contact-card";

  const header = document.createElement("div");
  header.className = "contact-card-header";

  const title = document.createElement("div");
  title.className = "contact-card-title";
  title.textContent = contact.unit_name || contact.office_name || "Contact";
  header.appendChild(title);

  card.appendChild(header);

  const details = document.createElement("div");
  details.className = "contact-card-details";

  if (phoneValues.length) {
    const phoneValue = createContactValueGroup(
      phoneValues,
      (value) => {
        const target = normalizePhoneTarget(value);
        return target ? `tel:${target}` : "";
      },
      "contact-link contact-link-phone",
    );

    if (phoneValue) {
      if (supportsWhatsApp) {
        phoneValue.prepend(createContactBadge("\u{1f4ac} WhatsApp", "contact-badge-whatsapp"));
      }

      details.appendChild(
        createContactDetailRow(
          "\u{1f4de}",
          supportsWhatsApp ? "WhatsApp/Call" : "Call",
          phoneValue,
        ),
      );
    }
  }

  if (emailValues.length) {
    const emailValue = createContactValueGroup(
      emailValues,
      (value) => {
        const target = normalizeEmailTarget(value);
        return isLikelyEmailAddress(target) ? `mailto:${target}` : "";
      },
      "contact-link contact-link-email",
    );

    if (emailValue) {
      details.appendChild(createContactDetailRow("\u2709\ufe0f", "Email", emailValue));
    }
  }

  if (office) {
    details.appendChild(createContactDetailRow("\u{1f4cd}", "Office", createPlainContactValue(office)));
  }

  if (officeHours) {
    details.appendChild(createContactDetailRow("\u{1f552}", "Hours", createPlainContactValue(officeHours)));
  }

  if (summary) {
    const summaryRow = document.createElement("div");
    summaryRow.className = "contact-summary-row";

    const summaryLabel = document.createElement("span");
    summaryLabel.className = "contact-summary-label";
    summaryLabel.textContent = "Supports:";

    const summaryValue = document.createElement("span");
    summaryValue.className = "contact-summary-value";
    summaryValue.textContent = summary;

    summaryRow.appendChild(summaryLabel);
    summaryRow.appendChild(summaryValue);
    details.appendChild(summaryRow);
  }

  if (details.children.length) {
    card.appendChild(details);
  }

  return card;
}

function cleanName(text) {
  const raw = String(text || "").trim();
  if (!raw || raw.includes("?")) return null;

  const stripped = raw.replace(/^[\s,;:.-]+/, "").replace(/[.\s]+$/, "").replace(/\s+/g, " ");
  const words = stripped.match(/[A-Za-z][A-Za-z'\-]*/g) || [];
  if (!words.length || words.length > 2) return null;

  const invalidWords = new Set([
    "does",
    "do",
    "did",
    "have",
    "has",
    "had",
    "what",
    "why",
    "who",
    "when",
    "where",
    "how",
    "want",
    "need",
    "eat",
    "girlfriend",
    "boyfriend",
    "student",
    "department",
    "level",
    "study",
    "studying",
    "call",
    "me",
    "my",
    "name",
  ]);

  if (words.some((word) => invalidWords.has(word.toLowerCase()))) return null;
  if (stripped.length > 30) return null;

  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join(" ");
}

function normalizeProfile(profile) {
  if (!profile || typeof profile !== "object") return null;

  const normalized = {};

  ["name", "department", "level"].forEach((key) => {
    const value = String(profile[key] || "").trim();
    if (key === "name") {
      const cleanedName = cleanName(value);
      if (cleanedName) {
        normalized[key] = cleanedName;
      }
      return;
    }

    if (value) {
      normalized[key] = value;
    }
  });

  if (Array.isArray(profile.notes)) {
    const notes = profile.notes
      .map((note) => String(note || "").trim())
      .filter(Boolean);
    if (notes.length) {
      normalized.notes = notes;
    }
  } else if (typeof profile.notes === "string") {
    const note = profile.notes.trim();
    if (note) {
      normalized.notes = [note];
    }
  }

  return Object.keys(normalized).length ? normalized : null;
}

function isMemoryControlMessage(message) {
  const normalized = normalizeText(message);
  if (!normalized) return false;

  const patterns = [
    /^call me\s+/,
    /^my name is\s+/,
    /^i am in\s+.+\s+department$/,
    /^i study\s+/,
    /^i m now\s+\d{2,3}\s*level$/,
    /^i am\s+\d{2,3}\s*level$/,
    /^i'm now\s+\d{2,3}\s*level$/,
    /^i m in\s+.+\s+department$/,
    /^i m studying\s+/,
    /^(change|update|set)\s+my\s+(name|department|level)\b/,
    /^(what is my name|whats my name|what's my name|what is my department|whats my department|what's my department|what level am i|what level am i in|what do you know about me|who am i)\b/,
    /^i prefer\s+/,
    /^i stay in\s+/,
    /^i stay at\s+/,
    /^i live in\s+/,
    /^i reside in\s+/,
  ];

  return patterns.some((pattern) => pattern.test(normalized));
}

function getSessionId() {
  try {
    const existing = localStorage.getItem(SESSION_KEY);
    if (existing) return existing;

    const generated =
      (window.crypto && typeof window.crypto.randomUUID === "function")
        ? window.crypto.randomUUID()
        : `sid_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(SESSION_KEY, generated);
    return generated;
  } catch (error) {
    console.error("Failed to create session id:", error);
    return `sid_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
}

async function clearServerProfile() {
  try {
    await fetch("/api/profile/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: getSessionId(),
      }),
    });
  } catch (error) {
    console.error("Failed to clear server profile:", error);
  }
}

function isGreetingResponse(text) {
  const normalized = normalizeText(text);
  if (!normalized) return false;

  return /^(hi|hello|hey|good morning|good afternoon|good evening)\b/.test(normalized);
}

function isShortResponse(text) {
  const normalized = normalizeText(text);
  if (!normalized) return true;

  return normalized.split(" ").filter(Boolean).length < 8;
}

function resetFeedbackCounter() {
  responseCount = 0;
}

function shouldShowFeedback(text, options = {}) {
  if (!options.feedbackCandidate) return false;
  if (options.isOnboardingMessage) return false;
  if (options.isAuxiliaryResponse) return false;
  if (isGreetingResponse(text)) return false;
  if (isShortResponse(text)) return false;
  return responseCount % 4 === 0;
}

function sendFeedback(payload) {
  return fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function setDisabledState(root, disabled) {
  const controls = root.querySelectorAll("button, textarea");
  controls.forEach((control) => {
    control.disabled = disabled;
  });
}

function attachFeedback(wrapper, userMessage, botResponse) {
  if (!userMessage || !botResponse) return;

  let submitted = false;
  const panel = document.createElement("div");
  panel.className = "feedback-panel";

  const question = document.createElement("div");
  question.className = "feedback-question";
  question.textContent = "Was this helpful?";

  const actions = document.createElement("div");
  actions.className = "feedback-actions";

  const status = document.createElement("div");
  status.className = "feedback-status";
  status.dataset.feedbackStatus = "true";

  const yesButton = document.createElement("button");
  yesButton.type = "button";
  yesButton.textContent = "Yes";

  const noButton = document.createElement("button");
  noButton.type = "button";
  noButton.textContent = "No";

  const renderThanks = () => {
    const thanks = document.createElement("div");
    thanks.className = "feedback-thanks";
    thanks.textContent = "Thanks for your feedback.";
    panel.replaceChildren(thanks);
  };

  const commitYes = async () => {
    if (submitted) return;
    submitted = true;
    setDisabledState(actions, true);
    panel.classList.add("feedback-submitted");
    actions.style.opacity = "0.55";
    actions.style.pointerEvents = "none";
    renderThanks();

    try {
      await sendFeedback({
        message: userMessage,
        response: botResponse,
        feedback: "yes",
      });
    } catch (error) {
      console.error(error);
    }
  };

  const showNoForm = () => {
    if (submitted) return;

    actions.remove();
    status.textContent = "Tell us what was wrong (optional)";

    const form = document.createElement("div");
    form.className = "feedback-comment";

    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.placeholder = "Add a short comment if you want";

    const submitButton = document.createElement("button");
    submitButton.type = "button";
    submitButton.className = "feedback-submit";
    submitButton.textContent = "Send feedback";

    submitButton.addEventListener("click", async () => {
      if (submitted) return;
      submitted = true;
      const comment = textarea.value.trim();
      setDisabledState(form, true);
      panel.classList.add("feedback-submitted");
      renderThanks();

      try {
        await sendFeedback({
          message: userMessage,
          response: botResponse,
          feedback: "no",
          comment,
        });
      } catch (error) {
        console.error(error);
      }
    });

    form.appendChild(textarea);
    form.appendChild(submitButton);
    panel.appendChild(form);
    panel.appendChild(status);
  };

  yesButton.addEventListener("click", commitYes);
  noButton.addEventListener("click", showNoForm);

  actions.appendChild(yesButton);
  actions.appendChild(noButton);
  panel.appendChild(question);
  panel.appendChild(actions);
  panel.appendChild(status);
  wrapper.appendChild(panel);
}

function addMessage(role, text, options = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;
  if (options.initialGreeting) {
    wrapper.dataset.initialGreeting = "true";
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "bot" && !options.instant) {
    typeText(bubble, text, 10);
  } else {
    bubble.textContent = text;
  }

  const stamp = document.createElement("span");
  stamp.className = "stamp";
  stamp.textContent = now();

  wrapper.appendChild(bubble);

  const contactCard = role === "bot" ? renderCompactContactCard(options.contact) : null;
  if (contactCard) {
    wrapper.classList.add("with-contact");
    wrapper.appendChild(contactCard);
  }

  wrapper.appendChild(stamp);

  if (role === "bot" && options.feedbackCandidate) {
    responseCount += 1;
    if (shouldShowFeedback(text, options)) {
      attachFeedback(wrapper, options.userMessage || lastUserMessage, text);
    }
  }

  if (options.insertBeforeEmptyState && emptyState && emptyState.parentNode === chatWindow) {
    chatWindow.insertBefore(wrapper, emptyState);
  } else {
    chatWindow.appendChild(wrapper);
  }
  chatWindow.scrollTop = chatWindow.scrollHeight;

  if (role === "user" && emptyState) {
    emptyState.style.display = "none";
  }

  return wrapper;
}

function showTyping() {
  typingIndicator.classList.remove("hidden");
}

function hideTyping() {
  typingIndicator.classList.add("hidden");
}

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function buildInitialGreeting(profile) {
  const normalized = normalizeProfile(profile) || null;
  const name = normalized && normalized.name ? normalized.name : "";
  const department = normalized && normalized.department ? normalized.department : "";
  const level = normalized && normalized.level ? normalized.level : "";

  if (name) {
    return `Welcome back, ${name}. I'm Governor AI. Tell me what you need and I'll help from there.`;
  }

  if (department && level) {
    return `Welcome back. I remember you are a ${level} level ${department} student. I'm Governor AI. Tell me what you need and I'll help from there.`;
  }

  if (department) {
    return `Welcome back. I remember your ${department} department details. I'm Governor AI. Tell me what you need and I'll help from there.`;
  }

  if (level) {
    return `Welcome back. I remember you are a ${level} level student. I'm Governor AI. Tell me what you need and I'll help from there.`;
  }

  if (normalized) {
    return "Welcome back. I'm Governor AI. Tell me what you need and I'll help from there.";
  }

  return `${getGreeting()}. I'm Governor AI. Tell me what you need and I'll help from there.`;
}

function renderInitialGreeting(greetingText) {
  const text = String(greetingText || "").trim() || buildInitialGreeting(userProfile);
  if (!text) return null;

  if (initialGreetingMessage && chatWindow.contains(initialGreetingMessage)) {
    const bubble = initialGreetingMessage.querySelector(".bubble");
    if (bubble) {
      bubble.textContent = text;
    }

    const stamp = initialGreetingMessage.querySelector(".stamp");
    if (stamp) {
      stamp.textContent = now();
    }

    chatWindow.scrollTop = chatWindow.scrollHeight;
    return initialGreetingMessage;
  }

  initialGreetingMessage = addMessage("bot", text, {
    initialGreeting: true,
    insertBeforeEmptyState: true,
  });
  return initialGreetingMessage;
}

function safeReadProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    return normalizeProfile(parsed);
  } catch (error) {
    console.error("Failed to read profile:", error);
    return null;
  }
}

function safeWriteProfile(profile) {
  try {
    const normalized = normalizeProfile(profile);
    if (!normalized) {
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch (error) {
    console.error("Failed to save profile:", error);
  }
}

function safeClearProfile() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    console.error("Failed to clear profile:", error);
  }
}

async function loadProfileFromServer() {
  try {
    const response = await fetch(`/api/profile?session_id=${encodeURIComponent(getSessionId())}`);
    if (!response.ok) return null;

    const data = await response.json();
    return {
      profile: normalizeProfile(data.profile),
      greeting: String(data.greeting || "").trim(),
    };
  } catch (error) {
    console.error("Failed to load server profile:", error);
    return null;
  }
}

function getActiveUserPayload() {
  if (userProfile) {
    return { ...userProfile };
  }

  return {};
}

function setWelcomeMessage() {
  return;
  if (!welcomeMessage) return;

  if (userProfile) {
    welcomeMessage.textContent = "Welcome back. Tell me what you need and I’ll help from there.";
    return;
  }

  welcomeMessage.textContent = "Good morning. I'm Governor AI. Tell me what you need and I’ll help from there.";
}

async function resetProfile() {
  await clearServerProfile();
  safeClearProfile();
  resetFeedbackCounter();
  userProfile = null;
  renderInitialGreeting(buildInitialGreeting(null));
  return;
}

async function initializeProfileState() {
  const localProfile = safeReadProfile();
  const serverState = await loadProfileFromServer();
  const serverProfile = serverState && serverState.profile ? serverState.profile : null;
  userProfile = normalizeProfile({
    ...(localProfile || {}),
    ...(serverProfile || {}),
  });

  if (userProfile) {
    safeWriteProfile(userProfile);
  }

  const greeting = (serverState && serverState.greeting) || buildInitialGreeting(userProfile);
  renderInitialGreeting(greeting);

  if (false) {
    addMessage("bot", "Good morning. I'm Governor AI. Tell me what you need and I’ll help from there.");
  }

  profileReady = true;
}

profileInitializationPromise = initializeProfileState();

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!profileReady && profileInitializationPromise) {
    await profileInitializationPromise;
  }

  const message = chatInput.value.trim();
  if (!message) return;
  console.log("User input:", message);

  const normalizedMessage = message.toLowerCase();
  lastUserMessage = message;

  addMessage("user", message);
  chatInput.value = "";

  if (normalizedMessage === "reset profile") {
    await resetProfile();
    return;
  }

  showTyping();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        user: getActiveUserPayload(),
        session_id: getSessionId(),
      }),
    });

    hideTyping();

    let data;
    try {
      data = await response.json();
    } catch (error) {
      console.error(error);
      addMessage("bot", "Something went wrong. Please try again.");
      return;
    }

    if (!response.ok) {
      addMessage("bot", data.error || "An error occurred.");
      return;
    }

    const fallback =
      "I'm here to help. Could you rephrase that or ask about academics, registration, or student life?";
    const reply = (data.reply || "").trim() || fallback;

    console.log("Confidence:", data.confidence);

    const returnedProfile = normalizeProfile(data.profile);
    if (returnedProfile) {
      userProfile = returnedProfile;
      safeWriteProfile(userProfile);
      renderInitialGreeting(buildInitialGreeting(userProfile));
    }

    addMessage("bot", reply, {
      feedbackCandidate: true,
      userMessage: message,
      contact: data.contact || null,
    });

    if (data.contact_suggestion) {
      addMessage("bot", data.contact_suggestion);
    }
  } catch (error) {
    console.error(error);
    hideTyping();
    addMessage("bot", "Something went wrong. Please try again.");
  } finally {
    hideTyping();
  }
});

const initial = document.querySelector("[data-init-time]");
if (initial) {
  initial.textContent = now();
}

const quickButtons = document.querySelectorAll("[data-quick]");
quickButtons.forEach((button) => {
  button.addEventListener("click", () => {
    chatInput.value = button.dataset.quick || "";
    chatInput.focus();
  });
});
