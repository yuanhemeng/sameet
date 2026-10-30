const createTab = document.querySelector("#create-tab");
const joinTab = document.querySelector("#join-tab");
const createForm = document.querySelector("#create-form");
const joinForm = document.querySelector("#join-form");
const formError = document.querySelector("#form-error");

function setMode(mode) {
  const creating = mode === "create";
  createTab.classList.toggle("active", creating);
  joinTab.classList.toggle("active", !creating);
  createTab.setAttribute("aria-selected", String(creating));
  joinTab.setAttribute("aria-selected", String(!creating));
  createForm.classList.toggle("hidden", !creating);
  joinForm.classList.toggle("hidden", creating);
  formError.textContent = "";
}

createTab.addEventListener("click", () => setMode("create"));
joinTab.addEventListener("click", () => setMode("join"));

document.querySelectorAll('input[name="time"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    document.querySelector("#custom-time-wrap").classList.toggle("hidden", radio.value !== "custom");
  });
});

function rememberIdentity(code, data, name) {
  localStorage.setItem(`sameet:${code}`, JSON.stringify({ playerId: data.playerId, token: data.token, name }));
  localStorage.setItem("sameet:lastName", name);
}

async function api(url, options) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "请求失败，请稍后再试");
  return data;
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = createForm.querySelector("button[type=submit]");
  const name = document.querySelector("#create-name").value.trim();
  const timeValue = document.querySelector('input[name="time"]:checked').value;
  const roundSeconds = timeValue === "custom" ? Number(document.querySelector("#custom-time").value) : Number(timeValue);
  formError.textContent = "";
  button.disabled = true;
  try {
    const data = await api("/api/rooms", { method: "POST", body: JSON.stringify({ name, round_seconds: roundSeconds }) });
    rememberIdentity(data.code, data, name);
    location.href = `/room/${data.code}`;
  } catch (error) {
    formError.textContent = error.message;
    button.disabled = false;
  }
});

joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = joinForm.querySelector("button[type=submit]");
  const name = document.querySelector("#join-name").value.trim();
  const code = document.querySelector("#room-code").value.trim().toUpperCase();
  formError.textContent = "";
  button.disabled = true;
  try {
    const data = await api(`/api/rooms/${encodeURIComponent(code)}/join`, { method: "POST", body: JSON.stringify({ name }) });
    rememberIdentity(data.code, data, name);
    location.href = `/room/${data.code}`;
  } catch (error) {
    formError.textContent = error.message;
    button.disabled = false;
  }
});

const lastName = localStorage.getItem("sameet:lastName") || "";
document.querySelector("#create-name").value = lastName;
document.querySelector("#join-name").value = lastName;

