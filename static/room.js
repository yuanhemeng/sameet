const code = location.pathname.split("/").filter(Boolean).pop().toUpperCase();
const storageKey = `sameet:${code}`;
let identity = JSON.parse(localStorage.getItem(storageKey) || "null");
let socket = null;
let currentState = null;
let reconnectTimer = null;
let countdownTimer = null;
let clockOffset = 0;

const $ = (selector) => document.querySelector(selector);
$("#room-code-display").textContent = code;

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(node.hideTimer);
  node.hideTimer = setTimeout(() => node.classList.remove("show"), 2200);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "请求失败，请稍后再试");
  return data;
}

function setConnection(status) {
  const wrap = $(".connection");
  wrap.classList.toggle("online", status === "online");
  wrap.classList.toggle("offline", status === "offline");
  $("#connection-text").textContent = status === "online" ? "已连接" : status === "offline" ? "正在重连" : "连接中";
}

function connect() {
  if (!identity) return;
  clearTimeout(reconnectTimer);
  setConnection("connecting");
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const query = new URLSearchParams({ player_id: identity.playerId, token: identity.token });
  socket = new WebSocket(`${protocol}://${location.host}/ws/${code}?${query}`);
  socket.addEventListener("open", () => setConnection("online"));
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") render(message);
    if (message.type === "error") toast(message.message);
  });
  socket.addEventListener("close", (event) => {
    setConnection("offline");
    if (event.code === 4401) {
      localStorage.removeItem(storageKey);
      identity = null;
      $("#join-dialog").showModal();
      return;
    }
    reconnectTimer = setTimeout(connect, 1800);
  });
}

function send(action, extra = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    toast("连接尚未恢复，请稍等");
    return;
  }
  socket.send(JSON.stringify({ action, ...extra }));
}

function renderPlayer(node, player) {
  node.classList.toggle("online", Boolean(player?.connected));
  node.classList.toggle("submitted", Boolean(player?.submitted));
  node.querySelector(".avatar").textContent = player ? player.name.slice(0, 1).toUpperCase() : "?";
  node.querySelector("strong").textContent = player?.name || "等待加入";
  node.querySelector("small").textContent = !player ? "尚未加入" : player.submitted ? "本轮已提交" : player.connected ? "在线" : "暂时离线";
}

function render(message) {
  currentState = message;
  const room = message.room;
  clockOffset = room.serverTime * 1000 - Date.now();
  renderPlayer($("#player-one"), room.players[0]);
  renderPlayer($("#player-two"), room.players[1]);

  const waiting = room.status === "waiting";
  const finished = room.status === "finished";
  $("#waiting-view").classList.toggle("hidden", !waiting);
  $("#game-view").classList.toggle("hidden", waiting || finished);
  $("#result-view").classList.toggle("hidden", !finished);

  if (waiting) renderWaiting(message);
  if (!waiting && !finished) renderGame(message);
  if (finished) renderResult(message);
  renderHistory(room.history);
}

function renderWaiting(message) {
  const room = message.room;
  const ready = room.players.length === 2 && room.players.every((player) => player.connected);
  const start = $("#start-game");
  start.classList.toggle("hidden", !message.you.isOwner);
  start.disabled = !ready;
  $("#waiting-copy").textContent = room.players.length < 2
    ? "把房间链接发给朋友，两人到齐后就可以开始。"
    : ready ? "两位玩家已到齐，准备开始吧。" : "朋友暂时离线，正在等待重新连接。";
}

function renderGame(message) {
  const room = message.room;
  $("#round-label").textContent = `第 ${room.round} 轮`;
  const last = room.history.at(-1);
  const pair = $("#previous-pair");
  if (last && room.status !== "reveal") {
    pair.innerHTML = last.answers.map((answer) => `<span>${escapeHtml(answer.word)}</span>`).join("");
    pair.classList.remove("hidden");
  } else if (room.status === "reveal" && last) {
    pair.innerHTML = last.answers.map((answer) => `<span>${escapeHtml(answer.word)}</span>`).join("");
    pair.classList.remove("hidden");
  } else {
    pair.classList.add("hidden");
  }

  const form = $("#word-form");
  const input = $("#word-input");
  const button = form.querySelector("button");
  const reveal = room.status === "reveal";
  input.disabled = message.you.submitted || reveal;
  button.disabled = message.you.submitted || reveal;
  if (!message.you.submitted && !reveal && document.activeElement !== input) input.value = "";

  if (reveal) {
    $("#game-prompt").textContent = "答案揭晓";
    $("#submission-note").textContent = "没有相同，下一轮继续靠近";
  } else if (room.status === "timed_out") {
    $("#game-prompt").textContent = "时间到了，仍然可以提交";
    $("#submission-note").textContent = message.you.submitted ? "已提交，正在等待对方" : "本轮已暂停，不用着急";
  } else {
    $("#game-prompt").textContent = room.round === 1 ? "写下你此刻想到的词" : "根据上一轮，再联想一个词";
    const submittedCount = room.players.filter((player) => player.submitted).length;
    $("#submission-note").textContent = message.you.submitted
      ? "已提交，正在等待对方"
      : submittedCount ? "对方已经提交" : "答案会在两人提交后同时揭晓";
  }
  startCountdown(room.deadline, room.status);
}

function startCountdown(deadline, status) {
  clearInterval(countdownTimer);
  const update = () => {
    if (!deadline || status !== "playing") {
      $("#timer").textContent = status === "reveal" ? "…" : "0";
      return;
    }
    const remaining = Math.max(0, Math.ceil((deadline * 1000 - (Date.now() + clockOffset)) / 1000));
    $("#timer").textContent = remaining;
  };
  update();
  countdownTimer = setInterval(update, 250);
}

function renderResult(message) {
  clearInterval(countdownTimer);
  const history = message.room.history;
  const finalRound = history.at(-1);
  $("#winning-word").textContent = finalRound?.answers[0]?.word || "相遇";
  $("#result-summary").textContent = `你们用了 ${history.length} 轮，终于想到了同一个词。`;
  $("#restart-game").classList.toggle("hidden", !message.you.isOwner);
}

function renderHistory(history) {
  const section = $("#history-section");
  section.classList.toggle("hidden", history.length === 0);
  $("#history-count").textContent = `${history.length} 轮`;
  $("#history-list").innerHTML = history.map((round) => `
    <li class="${round.matched ? "matched" : ""}">
      <span>第 ${round.round} 轮</span>
      ${round.answers.map((answer) => `<span class="history-word">${escapeHtml(answer.word)}<small>${escapeHtml(answer.name)}</small></span>`).join("")}
    </li>`).join("");
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "";
  return element.innerHTML;
}

$("#copy-link").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(location.href);
    toast("邀请链接已复制");
  } catch {
    toast("复制失败，请从地址栏复制链接");
  }
});
$("#start-game").addEventListener("click", () => send("start"));
$("#restart-game").addEventListener("click", () => send("restart"));
$("#word-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const word = $("#word-input").value.trim();
  if (word) send("submit", { word });
});

$("#dialog-join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const name = $("#dialog-name").value.trim();
  $("#dialog-error").textContent = "";
  button.disabled = true;
  try {
    const data = await api(`/api/rooms/${encodeURIComponent(code)}/join`, { method: "POST", body: JSON.stringify({ name }) });
    identity = { playerId: data.playerId, token: data.token, name };
    localStorage.setItem(storageKey, JSON.stringify(identity));
    localStorage.setItem("sameet:lastName", name);
    $("#join-dialog").close();
    connect();
  } catch (error) {
    $("#dialog-error").textContent = error.message;
    button.disabled = false;
  }
});

async function init() {
  if (identity) {
    connect();
    return;
  }
  $("#dialog-name").value = localStorage.getItem("sameet:lastName") || "";
  try {
    const room = await api(`/api/rooms/${encodeURIComponent(code)}`);
    if (!room.joinable) throw new Error("房间已满或游戏已经开始");
    $("#join-dialog").showModal();
  } catch (error) {
    $("#dialog-error").textContent = error.message;
    $("#dialog-join-form button").disabled = true;
    $("#join-dialog").showModal();
  }
}

init();
