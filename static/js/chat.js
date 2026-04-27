const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const typingIndicator = document.getElementById("typing-indicator");
const emptyState = document.getElementById("empty-state");
const welcomeMessage = document.getElementById("welcome");

function now() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function typeText(element, text, speed = 10) {
  let i = 0;
  function typing() {
    if (i < text.length) {
      element.innerHTML += text.charAt(i);
      i++;
      setTimeout(typing, speed);
    }
  }
  typing();
}

function addMessage(role, text) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "bot") {
    bubble.innerHTML = "";
    typeText(bubble, text, 10);
  } else {
    bubble.textContent = text;
  }

  const stamp = document.createElement("span");
  stamp.className = "stamp";
  stamp.textContent = now();

  wrapper.appendChild(bubble);
  wrapper.appendChild(stamp);
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

if (welcomeMessage) {
  welcomeMessage.textContent = `${getGreeting()} — I'm Governor AI. How can I assist you today?`;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = chatInput.value.trim();
  if (!message) return;
  console.log("User input:", message);

  addMessage("user", message);
  chatInput.value = "";
  showTyping();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
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
      "I'm here to help 😊. Could you rephrase that or ask about academics, registration, or student life?";
    const reply = (data.reply || "").trim() || fallback;

    console.log("Confidence:", data.confidence);
    addMessage("bot", reply);

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
