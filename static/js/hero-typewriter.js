const heroTexts = [
  "Welcome to Governor AI",
  "Your Guide at Godfrey Okoye University",
  "Ask anything about school processes",
];

let hIndex = 0;
let hChar = 0;
let hText = "";
let deleting = false;

function heroType() {
  const el = document.getElementById("hero-type");
  if (!el) return;

  if (deleting) {
    hText = heroTexts[hIndex].substring(0, hChar--);
  } else {
    hText = heroTexts[hIndex].substring(0, hChar++);
  }

  el.textContent = hText;

  if (!deleting && hChar === heroTexts[hIndex].length) {
    deleting = true;
    setTimeout(heroType, 1500);
    return;
  }

  if (deleting && hChar === 0) {
    deleting = false;
    hIndex = (hIndex + 1) % heroTexts.length;
  }

  setTimeout(heroType, deleting ? 40 : 70);
}

heroType();
