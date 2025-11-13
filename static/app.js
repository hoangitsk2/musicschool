document.addEventListener("DOMContentLoaded", () => {
  const playForm = document.getElementById("play-form");
  const volumeSlider = document.getElementById("volume-slider");
  const statusText = document.getElementById("status-text");
  const volumeValue = document.getElementById("volume-value");
  const powerValue = document.getElementById("power-value");
  const sessionEnd = document.getElementById("session-end");

  async function api(path, payload = {}, method = "POST") {
    const response = await fetch(`/api/${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      body: method === "GET" ? undefined : JSON.stringify(payload),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || response.statusText);
    }
    return response.json();
  }

  if (playForm) {
    playForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(playForm);
      const payload = Object.fromEntries(formData.entries());
      try {
        await api("play", payload);
        toast("Play command queued");
      } catch (error) {
        toast(error.message, true);
      }
    });
    playForm.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        try {
          await api(action);
          toast(`${action} command queued`);
        } catch (error) {
          toast(error.message, true);
        }
      });
    });
  }

  document.querySelectorAll("[data-power]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const desired = btn.dataset.power === "on";
      try {
        await api("power", { on: desired });
        toast(`Power ${desired ? "ON" : "OFF"} queued`);
      } catch (error) {
        toast(error.message, true);
      }
    });
  });

  document.querySelectorAll("[data-preview]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const trackId = Number(btn.dataset.preview);
      if (!trackId) {
        return;
      }
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Queued...";
      try {
        await api("preview", { track_id: trackId });
        toast("Preview command queued");
      } catch (error) {
        toast(error.message, true);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  if (volumeSlider) {
    let debounce;
    volumeSlider.addEventListener("input", () => {
      volumeValue.textContent = volumeSlider.value;
      clearTimeout(debounce);
      debounce = setTimeout(async () => {
        try {
          await api("volume", { volume: Number(volumeSlider.value) });
          toast("Volume updated");
        } catch (error) {
          toast(error.message, true);
        }
      }, 300);
    });
  }

  async function refreshStatus() {
    try {
      const data = await api("status", {}, "GET");
      if (statusText) {
        statusText.textContent = (data.status || "idle").toUpperCase();
      }
      if (volumeValue) {
        volumeValue.textContent = data.volume;
      }
      if (powerValue) {
        powerValue.textContent = data.power_on ? "ON" : "OFF";
      }
      if (sessionEnd) {
        sessionEnd.textContent = data.session_end_at || "—";
      }
      if (volumeSlider) {
        volumeSlider.value = data.volume;
      }
    } catch (error) {
      console.error(error);
    }
  }

  function toast(message, error = false) {
    const toastContainer = document.getElementById("toast-container") || createToastContainer();
    const toastEl = document.createElement("div");
    toastEl.className = `alert ${error ? "alert-error" : "alert-success"}`;
    toastEl.innerHTML = `<span>${message}</span>`;
    toastContainer.appendChild(toastEl);
    setTimeout(() => {
      toastEl.remove();
    }, 4000);
  }

  function createToastContainer() {
    const container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast toast-end toast-top";
    document.body.appendChild(container);
    return container;
  }

  refreshStatus();
  setInterval(refreshStatus, 2000);
});
