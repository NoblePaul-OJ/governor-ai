const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const typingIndicator = document.getElementById("typing-indicator");
const emptyState = document.getElementById("empty-state");
const welcomeMessage = document.getElementById("welcome");
const STORAGE_KEY = "governor_user";
const SESSION_KEY = "governor_session_id";

let userProfile = null;
let lastUserMessage = "";
let responseCount = 0;
let profileReady = false;
let profileInitializationPromise = null;
let onboardingStep = 0;
let onboardingActive = false;
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

function normalizeText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeProfile(profile) {
  if (!profile || typeof profile !== "object") return null;

  const normalized = {};

  ["name", "department", "level"].forEach((key) => {
    const value = String(profile[key] || "").trim();
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

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "bot") {
    typeText(bubble, text, 10);
  } else {
    bubble.textContent = text;
  }

  const stamp = document.createElement("span");
  stamp.className = "stamp";
  stamp.textContent = now();

  wrapper.appendChild(bubble);
  wrapper.appendChild(stamp);

  if (role === "bot" && options.feedbackCandidate) {
    responseCount += 1;
    if (shouldShowFeedback(text, options)) {
      attachFeedback(wrapper, options.userMessage || lastUserMessage, text);
    }
  }

  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  if (role === "user" && emptyState) {
    emptyState.style.display = "none";
  }
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
    return normalizeProfile(data.profile);
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
  if (!welcomeMessage) return;

  if (userProfile) {
    if (userProfile.name) {
      welcomeMessage.textContent = `Welcome back, ${userProfile.name}. How can I assist you today?`;
    } else {
      welcomeMessage.textContent = "Welcome back. How can I assist you today?";
    }
    return;
  }

  welcomeMessage.textContent = "Good morning - I'm Governor AI. How can I assist you today?";
}

function resetProfile() {
  clearServerProfile();
  safeClearProfile();
  resetFeedbackCounter();
  userProfile = null;
  setWelcomeMessage();
  addMessage("bot", "Good morning - I'm Governor AI. How can I assist you today?");
}

async function initializeProfileState() {
  const localProfile = safeReadProfile();
  const serverProfile = await loadProfileFromServer();
  userProfile = normalizeProfile({
    ...(localProfile || {}),
    ...(serverProfile || {}),
  });

  if (userProfile) {
    safeWriteProfile(userProfile);
  }

  setWelcomeMessage();

  if (!userProfile) {
    addMessage("bot", "Good morning - I'm Governor AI. How can I assist you today?");
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
    resetProfile();
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
      setWelcomeMessage();
    }

    addMessage("bot", reply, {
      feedbackCandidate: true,
      userMessage: message,
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
