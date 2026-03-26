(() => {
  const root = document.querySelector("[data-chat-root]");
  if (!root) return;

  const messages = root.querySelector("[data-chat-messages]");
  const input = root.querySelector("[data-chat-input]");
  const sendBtn = root.querySelector("[data-chat-send]");
  const resetBtn = root.querySelector("[data-chat-reset]");
  const suggestionBox = root.querySelector("[data-chat-suggestions]");
  const paymentPanel = root.querySelector("[data-payment]");
  const paymentAmount = root.querySelector("[data-payment-amount]");
  const paymentMethod = root.querySelector("[data-payment-method]");
  const paymentConfirm = root.querySelector("[data-payment-confirm]");
  const voiceToggle = root.querySelector("[data-voice-toggle]");
  const speakToggle = root.querySelector("[data-speak-toggle]");
  const voiceStatus = root.querySelector("[data-voice-status]");
  const emptyHint = root.querySelector(".chat-empty");
  const summaryPanel = root.querySelector("[data-trip-summary]");
  const summaryEmpty = root.querySelector("[data-summary-empty]");
  const summaryGrid = root.querySelector("[data-summary-grid]");
  const trainCards = root.querySelector("[data-train-cards]");
  const ticketGrid = root.querySelector("[data-ticket-grid]");
  const ticketEmpty = root.querySelector("[data-ticket-empty]");

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const supportsSpeechInput = Boolean(SpeechRecognition);
  const supportsSpeechOutput = "speechSynthesis" in window;

  const suggestions = [
    "Book ticket",
    "Check PNR",
    "Seat availability",
    "Live status",
    "Tatkal booking",
    "Fare comparison",
    "Cancel ticket",
    "E-catering",
    "Wallet balance"
  ];

  const seatChoicesByClass = {
    SL: ["Lower", "Middle", "Upper", "Side Lower", "Side Upper", "No preference"],
    "3A": ["Lower", "Middle", "Upper", "Side Lower", "Side Upper", "No preference"],
    "2A": ["Lower", "Upper", "Side Lower", "Side Upper", "No preference"],
    "1A": ["Lower", "Upper", "Cabin", "Coupe", "No preference"],
    CC: ["Window", "Aisle", "No preference"],
    EC: ["Window", "Aisle", "No preference"],
    "2S": ["Window", "Aisle", "No preference"]
  };

  let pendingPaymentToken = null;
  let speechEnabled = supportsSpeechOutput;
  let recognition = null;
  let listening = false;
  let currentSummary = null;

  const resizeComposer = () => {
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  };

  const setVoiceStatus = text => {
    if (voiceStatus) voiceStatus.textContent = text;
  };

  const syncVoiceButtons = () => {
    if (voiceToggle) {
      voiceToggle.classList.toggle("is-active", listening);
      voiceToggle.textContent = listening ? "Listening..." : "Talk";
      voiceToggle.disabled = !supportsSpeechInput;
    }
    if (speakToggle) {
      speakToggle.classList.toggle("is-active", speechEnabled);
      speakToggle.textContent = speechEnabled ? "Speaker On" : "Speaker Off";
      speakToggle.disabled = !supportsSpeechOutput;
    }
  };

  const speakText = text => {
    if (!speechEnabled || !supportsSpeechOutput || !text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
  };

  if (supportsSpeechInput) {
    recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onstart = () => {
      listening = true;
      setVoiceStatus("Listening for your message...");
      syncVoiceButtons();
    };

    recognition.onresult = event => {
      const transcript = Array.from(event.results)
        .map(result => result[0]?.transcript || "")
        .join("")
        .trim();
      input.value = transcript;
      resizeComposer();
      if (event.results[event.results.length - 1]?.isFinal && transcript) {
        setVoiceStatus("Sending your voice message...");
        sendMessage(transcript);
      }
    };

    recognition.onerror = event => {
      listening = false;
      setVoiceStatus(event.error === "not-allowed" ? "Microphone permission denied" : "Voice input unavailable");
      syncVoiceButtons();
    };

    recognition.onend = () => {
      listening = false;
      if (voiceStatus && voiceStatus.textContent === "Listening for your message...") {
        setVoiceStatus("Voice ready");
      }
      syncVoiceButtons();
    };
  } else {
    setVoiceStatus("Voice input not supported in this browser");
  }

  const addMessage = (text, who = "bot") => {
    const wrapper = document.createElement("div");
    wrapper.className = `chat-msg ${who}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
    updateEmptyHint();
    if (who === "bot") {
      speakText(text);
    }
  };

  const setSummaryField = (selector, value) => {
    const node = root.querySelector(selector);
    if (node) node.textContent = value || "-";
  };

  const renderSummary = summary => {
    if (!summaryPanel) return;
    if (!summary) {
      summaryEmpty?.classList.remove("hidden");
      summaryGrid?.classList.add("hidden");
      return;
    }
    summaryEmpty?.classList.add("hidden");
    summaryGrid?.classList.remove("hidden");
    setSummaryField("[data-summary-mode]", summary.mode || "-");
    setSummaryField("[data-summary-route]", summary.from && summary.to ? `${summary.from} -> ${summary.to}` : "-");
    setSummaryField("[data-summary-date]", summary.date || "-");
    setSummaryField("[data-summary-class]", summary.class || "-");
    setSummaryField("[data-summary-quota]", summary.quota || "-");
    setSummaryField("[data-summary-passengers]", summary.passenger_count ? String(summary.passenger_count) : "-");
    setSummaryField("[data-summary-seat]", summary.seat_preferences || "-");
    setSummaryField("[data-summary-coach]", summary.coach_preference || "-");
    setSummaryField("[data-summary-fare]", summary.fare ? `Rs ${summary.fare}` : "-");
    setSummaryField("[data-summary-train]", summary.train ? `${summary.train.number || ""} ${summary.train.name || ""}`.trim() : "-");
  };

  const contextualSuggestions = summary => {
    if (!summary?.step) return [];
    if (summary.step === "quota") return ["General", "Tatkal", "Ladies", "Senior"];
    if (summary.step === "class") return ["SL", "3A", "2A", "1A", "CC", "EC", "2S"];
    if (summary.step === "payment") return ["UPI", "Card", "R-Wallet"];
    if (summary.step === "coach_preference") return ["Front", "Middle", "Rear", "No preference"];
    if (summary.step === "seat_preference") return seatChoicesByClass[summary.class] || ["No preference"];
    return [];
  };

  const renderTrainCards = cards => {
    if (!trainCards) return;
    if (!cards || !cards.length) {
      trainCards.classList.add("hidden");
      trainCards.innerHTML = "";
      return;
    }
    trainCards.classList.remove("hidden");
    trainCards.innerHTML = cards.map(card => `
      <article class="train-card">
        <div class="train-card-top">
          <strong>${card.number} ${card.name}</strong>
          <span>${card.duration || ""}</span>
        </div>
        <div class="train-card-route">${card.from || ""} -> ${card.to || ""}</div>
        <div class="train-card-time">${card.dep || "--:--"} to ${card.arr || "--:--"}</div>
        <div class="train-card-classes">${(card.classes || []).join(", ")}</div>
      </article>
    `).join("");
  };

  const renderTickets = tickets => {
    if (!ticketGrid) return;
    if (!tickets || !tickets.length) {
      ticketGrid.innerHTML = "";
      ticketEmpty?.classList.remove("hidden");
      return;
    }
    ticketEmpty?.classList.add("hidden");
    ticketGrid.innerHTML = tickets.map(ticket => `
      <article class="ticket-card">
        <div class="ticket-band">
          <span class="ticket-brand">RailSmart e-Ticket</span>
          <span class="ticket-status">CONFIRMED</span>
        </div>
        <div class="ticket-main">
          <div class="ticket-route">
            <div>
              <span class="ticket-label">From</span>
              <strong>${ticket.from || "-"}</strong>
            </div>
            <div class="ticket-arrow">-></div>
            <div>
              <span class="ticket-label">To</span>
              <strong>${ticket.to || "-"}</strong>
            </div>
          </div>
          <div class="ticket-train-line">
            <span>${ticket.train?.number || ""} ${ticket.train?.name || ""}</span>
            <span>${ticket.train?.dep || "--:--"} - ${ticket.train?.arr || "--:--"}</span>
          </div>
          <div class="ticket-meta">
            <span><strong>PNR:</strong> ${ticket.pnr || "-"}</span>
            <span><strong>Date:</strong> ${ticket.journey_date || "-"}</span>
            <span><strong>Class:</strong> ${ticket.class || "-"}</span>
            <span><strong>Quota:</strong> ${ticket.quota || "-"}</span>
            <span><strong>Coach Pref:</strong> ${ticket.coach_preference || "No preference"}</span>
            <span><strong>Fare:</strong> Rs ${ticket.fare || "-"}</span>
            <span><strong>Payment:</strong> ${ticket.payment_method || "-"}</span>
          </div>
          <div class="ticket-passengers">
            <span class="ticket-label">Passengers</span>
            <div>
              ${(ticket.passengers || []).map(passenger => `
                <span class="passenger-chip">${passenger.name} / ${passenger.age} / ${passenger.gender} / ${passenger.food} / Pref: ${passenger.seat_preference || "No preference"} / Seat: ${passenger.coach || "-"}-${passenger.seat_no || "-"} ${passenger.assigned_seat || "-"}</span>
              `).join("")}
            </div>
          </div>
        </div>
        <div class="ticket-actions">
          <a class="button" href="/ticket/${ticket.pnr}/pdf">Download PDF</a>
        </div>
      </article>
    `).join("");
  };

  const renderSuggestions = (value = "") => {
    const query = value.trim().toLowerCase();
    const source = !query && currentSummary ? contextualSuggestions(currentSummary) : suggestions;
    const pool = query ? [...new Set([...contextualSuggestions(currentSummary), ...suggestions])].filter(item => item.toLowerCase().includes(query)) : source;
    const limit = query ? 6 : (currentSummary ? 6 : 3);
    const items = pool.slice(0, limit);
    suggestionBox.innerHTML = "";
    if (!items.length) return;
    items.forEach(item => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = item;
      btn.addEventListener("click", () => {
        input.value = item;
        sendMessage();
      });
      suggestionBox.appendChild(btn);
    });
  };

  const showPayment = action => {
    pendingPaymentToken = action.token;
    paymentAmount.textContent = `Rs ${action.amount}`;
    paymentMethod.textContent = action.method;
    paymentPanel.hidden = false;
  };

  const hidePayment = () => {
    pendingPaymentToken = null;
    paymentPanel.hidden = true;
  };

  async function sendMessage(overrideText) {
    const text = (overrideText ?? input.value).trim();
    if (!text) return;
    sendBtn.disabled = true;
    root.querySelector(".chat-input").classList.add("is-busy");
    addMessage(text, "user");
    input.value = "";
    resizeComposer();
    suggestionBox.innerHTML = "";
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });
      const data = await resp.json();
      if (data.reply) {
        addMessage(data.reply, "bot");
      }
      if ("summary" in data) {
        currentSummary = data.summary || null;
        renderSummary(data.summary);
      }
      if (data.train_cards) {
        renderTrainCards(data.train_cards);
      }
      if (data.tickets) {
        renderTickets(data.tickets);
      }
      if (data.ticket_download?.url) {
        addMessage(`Download: ${data.ticket_download.url}`, "bot");
      }
      if (data.action && data.action.type === "payment") {
        showPayment(data.action);
      }
      if (text && voiceStatus) {
        setVoiceStatus("Voice ready");
      }
    } catch (_) {
      addMessage("Sorry, I hit an error. Please try again.", "bot");
    } finally {
      sendBtn.disabled = false;
      root.querySelector(".chat-input").classList.remove("is-busy");
      renderSuggestions("");
    }
  }

  const resetChat = async () => {
    try {
      await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: "__reset__" })
      });
    } catch (_) {}
    messages.innerHTML = "";
    if (emptyHint) {
      messages.appendChild(emptyHint);
    }
    addMessage("Chat reset. What would you like to do next?", "bot");
    currentSummary = null;
    renderSummary(null);
    renderTrainCards([]);
    hidePayment();
    renderSuggestions("");
    setVoiceStatus(supportsSpeechInput ? "Voice ready" : "Voice input not supported in this browser");
  };

  const updateEmptyHint = () => {
    if (!emptyHint) return;
    const hasUserMessages = messages.querySelectorAll(".chat-msg.user").length > 0;
    emptyHint.style.display = hasUserMessages ? "none" : "block";
  };

  input.addEventListener("input", e => {
    resizeComposer();
    renderSuggestions(e.target.value);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  sendBtn.addEventListener("click", () => sendMessage());
  resetBtn.addEventListener("click", resetChat);

  root.querySelectorAll("[data-quick]").forEach(btn => {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.quick || btn.textContent;
      sendMessage();
    });
  });

  paymentConfirm.addEventListener("click", async () => {
    if (!pendingPaymentToken) return;
    try {
      const resp = await fetch("/api/pay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: pendingPaymentToken })
      });
      const data = await resp.json();
      if (data.reply) {
        addMessage(data.reply, "bot");
      }
      currentSummary = null;
      renderSummary(null);
      renderTrainCards([]);
      if (data.tickets) {
        renderTickets(data.tickets);
      }
      if (data.ticket_download?.url) {
        addMessage(`Download: ${data.ticket_download.url}`, "bot");
      }
    } catch (_) {
      addMessage("Payment failed. Please try again.", "bot");
    }
    hidePayment();
  });

  if (voiceToggle) {
    voiceToggle.addEventListener("click", () => {
      if (!recognition) {
        setVoiceStatus("Voice input not supported in this browser");
        return;
      }
      if (listening) {
        recognition.stop();
      } else {
        window.speechSynthesis?.cancel();
        recognition.start();
      }
    });
  }

  if (speakToggle) {
    speakToggle.addEventListener("click", () => {
      speechEnabled = !speechEnabled;
      if (!speechEnabled && supportsSpeechOutput) {
        window.speechSynthesis.cancel();
      }
      setVoiceStatus(speechEnabled ? "Voice replies enabled" : "Voice replies muted");
      syncVoiceButtons();
    });
  }

  hidePayment();
  updateEmptyHint();
  renderSuggestions("");
  resizeComposer();
  syncVoiceButtons();
})();
