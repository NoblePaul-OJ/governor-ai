const typewriterTarget = document.getElementById("typewriter");

if (typewriterTarget) {
  const texts = [
    "Ask about course registration...",
    "Need help with hostel accommodation?",
    "Confused about school fees?",
    "Governor AI is here to guide you...",
  ];

  let index = 0;
  let charIndex = 0;
  let currentText = "";
  let isDeleting = false;

  function typeEffect() {
    if (!typewriterTarget) return;

    if (isDeleting) {
      currentText = texts[index].substring(0, charIndex--);
    } else {
      currentText = texts[index].substring(0, charIndex++);
    }

    typewriterTarget.textContent = currentText;

    if (!isDeleting && charIndex === texts[index].length) {
      isDeleting = true;
      setTimeout(typeEffect, 1500);
      return;
    }

    if (isDeleting && charIndex === 0) {
      isDeleting = false;
      index = (index + 1) % texts.length;
    }

    setTimeout(typeEffect, isDeleting ? 40 : 80);
  }

  typeEffect();
}
