const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const typingIndicator = document.getElementById("typing-indicator");
const emptyState = document.getElementById("empty-state");
const welcomeMessage = document.getElementById("welcome");
const STORAGE_KEY = "governor_user";

let userProfile = null;
let lastUserMessage = "";
let responseCount = 0;
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
    if (!parsed || typeof parsed !== "object") return null;

    const name = String(parsed.name || "").trim();
    const department = String(parsed.department || "").trim();
    const level = String(parsed.level || "").trim();

    if (!name || !department || !level) return null;

    return { name, department, level };
  } catch (error) {
    console.error("Failed to read profile:", error);
    return null;
  }
}

function safeWriteProfile(profile) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
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

function getActiveUserPayload() {
  if (userProfile) {
    return { ...userProfile };
  }

  return {
    name: onboardingDraft.name || "",
    department: onboardingDraft.department || "",
    level: onboardingDraft.level || "",
  };
}

function setWelcomeMessage() {
  if (!welcomeMessage) return;

  if (userProfile) {
    welcomeMessage.textContent = `Welcome back, ${userProfile.name}. How can I assist you today?`;
    return;
  }

  welcomeMessage.textContent = `${getGreeting()} - let's personalize your experience.`;
}

function completeOnboarding() {
  userProfile = {
    name: onboardingDraft.name,
    department: onboardingDraft.department,
    level: onboardingDraft.level,
  };

  safeWriteProfile(userProfile);
  onboardingActive = false;
  onboardingStep = 0;
  setWelcomeMessage();
  addMessage(
    "bot",
    `Nice to meet you, ${userProfile.name}. I'll guide you better based on your ${userProfile.department} ${userProfile.level} level.`
  );
}

function handleOnboardingAnswer(message) {
  if (onboardingStep === 0) {
    onboardingDraft.name = message;
    onboardingStep = 1;
    addMessage("bot", "What is your department?");
    return;
  }

  if (onboardingStep === 1) {
    onboardingDraft.department = message;
    onboardingStep = 2;
    addMessage("bot", "What is your level? (e.g., 100, 200, 300...)");
    return;
  }

  onboardingDraft.level = message;
  completeOnboarding();
}

function startOnboarding(reason = "initial") {
  onboardingActive = true;
  onboardingStep = 0;
  onboardingDraft = {
    name: "",
    department: "",
    level: "",
  };

  if (emptyState) {
    emptyState.style.display = "none";
  }

  if (reason === "reset") {
    addMessage("bot", "Profile cleared. Let's start over.");
  }

  addMessage("bot", "What should I call you?");
}

function resetProfile() {
  safeClearProfile();
  resetFeedbackCounter();
  userProfile = null;
  onboardingActive = false;
  onboardingStep = 0;
  onboardingDraft = {
    name: "",
    department: "",
    level: "",
  };
  setWelcomeMessage();
  startOnboarding("reset");
}

userProfile = safeReadProfile();
setWelcomeMessage();

if (!userProfile) {
  startOnboarding();
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

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

  if (onboardingActive) {
    handleOnboardingAnswer(message);
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
