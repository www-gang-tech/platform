(function () {
  "use strict";

  var TOKEN_KEY = "gang.ask.token";
  var state = {
    token: "",
    principal: null,
    sessionId: "",
    busy: false
  };

  var nodes = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function text(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return String(value);
  }

  function array(value) {
    return Array.isArray(value) ? value : [];
  }

  function el(tag, className, value) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (value !== undefined && value !== null) {
      node.textContent = text(value);
    }
    return node;
  }

  function appendText(parent, value) {
    parent.appendChild(document.createTextNode(text(value)));
  }

  function authHeaders() {
    return {
      "Authorization": "Bearer " + state.token,
      "Content-Type": "application/json"
    };
  }

  function api(path, options) {
    var next = options || {};
    next.headers = next.headers || authHeaders();
    return fetch(path, next).then(function (response) {
      if (response.status === 401) {
        forgetToken();
        showConnect("That token is not valid for this device.");
        throw new Error("unauthorized");
      }
      return response.json().then(function (payload) {
        if (!response.ok) {
          throw new Error(errorMessage(payload));
        }
        return payload;
      });
    });
  }

  function errorMessage(payload) {
    var error = payload && payload.error;
    return text(error && error.message) || "The request could not be completed.";
  }

  function storeToken(token) {
    state.token = token;
    localStorage.setItem(TOKEN_KEY, token);
  }

  function forgetToken() {
    state.token = "";
    state.principal = null;
    state.sessionId = "";
    localStorage.removeItem(TOKEN_KEY);
  }

  function showConnect(message) {
    nodes.connectView.classList.remove("hidden");
    nodes.chatView.classList.add("hidden");
    nodes.connectError.textContent = text(message);
    nodes.tokenInput.value = "";
    nodes.tokenInput.focus();
  }

  function showChat() {
    nodes.connectView.classList.add("hidden");
    nodes.chatView.classList.remove("hidden");
    nodes.principalName.textContent = text(state.principal && state.principal.display_name);
  }

  function setStatus(value) {
    nodes.answerStatus.textContent = text(value);
  }

  function setBusy(value) {
    state.busy = Boolean(value);
    nodes.sendButton.disabled = state.busy;
    nodes.questionInput.disabled = state.busy;
  }

  function selectedLevel() {
    var checked = document.querySelector("input[name='level']:checked");
    var level = checked ? checked.value : "normal";
    return level === "fast" ? "fast" : "normal";
  }

  function buildAskPayload(question, sessionId, level) {
    var payload = {
      question: text(question).trim(),
      level: level === "fast" ? "fast" : "normal"
    };
    if (sessionId) {
      payload.session_id = text(sessionId);
    }
    return payload;
  }

  function boot() {
    nodes = {
      connectView: byId("connect-view"),
      chatView: byId("chat-view"),
      connectForm: byId("connect-form"),
      connectError: byId("connect-error"),
      tokenInput: byId("token-input"),
      principalName: byId("principal-name"),
      forgetDevice: byId("forget-device"),
      newConversation: byId("new-conversation"),
      sessionList: byId("session-list"),
      thread: byId("thread"),
      composer: byId("composer"),
      questionInput: byId("question-input"),
      sendButton: byId("send-button"),
      answerStatus: byId("answer-status")
    };

    nodes.connectForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var token = text(nodes.tokenInput.value).trim();
      if (!token) {
        nodes.connectError.textContent = "Paste the device token to continue.";
        return;
      }
      storeToken(token);
      verifyToken();
    });

    nodes.forgetDevice.addEventListener("click", function () {
      forgetToken();
      showConnect("This device has been forgotten.");
    });

    nodes.newConversation.addEventListener("click", function () {
      state.sessionId = "";
      renderEmptyThread();
      markActiveSession();
      nodes.questionInput.focus();
    });

    nodes.composer.addEventListener("submit", function (event) {
      event.preventDefault();
      submitQuestion();
    });

    state.token = localStorage.getItem(TOKEN_KEY) || "";
    if (!state.token) {
      showConnect("");
      return;
    }
    verifyToken();
  }

  function verifyToken() {
    nodes.connectError.textContent = "";
    return api("/v1/whoami", { method: "GET", headers: authHeaders() })
      .then(function (principal) {
        state.principal = principal;
        showChat();
        renderEmptyThread();
        return loadSessions();
      })
      .catch(function (error) {
        if (text(error.message) !== "unauthorized") {
          forgetToken();
          showConnect("The device token could not be verified.");
        }
      });
  }

  function loadSessions() {
    return api("/v1/sessions", { method: "GET", headers: authHeaders() })
      .then(function (payload) {
        renderSessions(array(payload.sessions));
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function renderSessions(sessions) {
    nodes.sessionList.replaceChildren();
    if (!sessions.length) {
      nodes.sessionList.appendChild(el("p", "meta", "No saved conversations yet."));
      return;
    }
    sessions.forEach(function (session) {
      var item = el("div", "session-item");
      var select = el("button", "session-select");
      select.type = "button";
      select.dataset.sessionId = text(session.session_id);
      var title = text(array(session.active_topics)[0]) || "Conversation";
      select.appendChild(el("span", "", title));
      select.appendChild(el("span", "meta", sessionMeta(session)));
      select.addEventListener("click", function () {
        loadSession(text(session.session_id));
      });

      var remove = el("button", "session-delete", "Delete");
      remove.type = "button";
      remove.addEventListener("click", function () {
        deleteSession(text(session.session_id));
      });

      item.appendChild(select);
      item.appendChild(remove);
      nodes.sessionList.appendChild(item);
    });
    markActiveSession();
  }

  function sessionMeta(session) {
    var turns = Number(session.turn_count || 0);
    var label = turns === 1 ? "1 turn" : String(turns) + " turns";
    var updated = text(session.updated);
    return updated ? label + " · " + updated : label;
  }

  function markActiveSession() {
    var buttons = nodes.sessionList.querySelectorAll(".session-select");
    buttons.forEach(function (button) {
      var active = text(button.dataset.sessionId) === text(state.sessionId);
      button.classList.toggle("active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
  }

  function loadSession(sessionId) {
    if (!sessionId) {
      return;
    }
    api("/v1/sessions/" + encodeURIComponent(sessionId), { method: "GET", headers: authHeaders() })
      .then(function (payload) {
        state.sessionId = sessionId;
        renderSession(payload.session || {});
        markActiveSession();
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function deleteSession(sessionId) {
    if (!sessionId) {
      return;
    }
    api("/v1/sessions/" + encodeURIComponent(sessionId), { method: "DELETE", headers: authHeaders() })
      .then(function () {
        if (state.sessionId === sessionId) {
          state.sessionId = "";
          renderEmptyThread();
        }
        return loadSessions();
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function renderEmptyThread() {
    nodes.thread.replaceChildren();
    nodes.thread.appendChild(el("p", "empty-note", "Ask a private corpus question. Answers stay grounded in cited evidence, and recommendations are separated from recorded facts."));
    setStatus("");
  }

  function renderSession(session) {
    nodes.thread.replaceChildren();
    var turns = array(session.turns);
    if (!turns.length) {
      renderEmptyThread();
      return;
    }
    turns.forEach(function (turn) {
      appendUserMessage(text(turn.question));
      var assistant = el("article", "message assistant");
      assistant.appendChild(el("p", "mode-label", modeLabel(turn.mode)));
      assistant.appendChild(el("p", "answer-body", text(turn.answer_summary) || "Earlier answer summary is unavailable."));
      nodes.thread.appendChild(assistant);
    });
    scrollThread();
  }

  function appendUserMessage(question) {
    var message = el("article", "message user");
    message.appendChild(el("p", "", question));
    nodes.thread.appendChild(message);
  }

  function submitQuestion() {
    if (state.busy) {
      return;
    }
    var question = text(nodes.questionInput.value).trim();
    if (!question) {
      return;
    }
    if (nodes.thread.querySelector(".empty-note")) {
      nodes.thread.replaceChildren();
    }
    appendUserMessage(question);
    nodes.questionInput.value = "";
    setBusy(true);
    setStatus("Waiting...");
    api("/v1/ask", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(buildAskPayload(question, state.sessionId, selectedLevel()))
    })
      .then(function (job) {
        return pollJob(text(job.job_id));
      })
      .then(function (result) {
        setBusy(false);
        setStatus("");
        state.sessionId = text(result.session_id) || state.sessionId;
        renderAssistantResult(nodes.thread, result);
        scrollThread();
        loadSessions();
      })
      .catch(function (error) {
        setBusy(false);
        setStatus(error.message);
      });
  }

  function pollJob(jobId) {
    return api("/v1/jobs/" + encodeURIComponent(jobId) + "?block=20", {
      method: "GET",
      headers: authHeaders()
    }).then(function (job) {
      var status = text(job.status);
      if (status === "queued") {
        setStatus("Waiting...");
        return pollJob(jobId);
      }
      if (status === "running") {
        setStatus("Thinking...");
        return pollJob(jobId);
      }
      if (status === "succeeded" || status === "done") {
        return job.result || {};
      }
      if (status === "failed" || status === "error") {
        throw new Error(errorMessage(job));
      }
      if (status === "timeout" || status === "provider-timeout") {
        throw new Error("The local answer timed out.");
      }
      throw new Error("The answer stopped in an unknown state.");
    });
  }

  function renderAssistantResult(parent, result) {
    var message = el("article", "message assistant");
    var mode = text(result && result.intent && result.intent.mode);
    var advisory = mode === "advisory";
    message.appendChild(el("p", "mode-label", advisory ? "Advisory" : "Evidence"));

    var grouped = groupClaims(array(result && result.claims));
    var answer = text(result && result.answer);
    message.appendChild(el("p", "answer-body", answer || "No answer text was returned."));

    if (advisory) {
      appendClaimSection(message, "Evidence", grouped.facts, "fact");
    }
    appendClaimSection(message, "Inference", grouped.inferences, "inference");
    appendRecommendationSection(message, grouped.recommendations);

    appendStatusBlock(message, result || {});
    appendSources(message, array(result && result.sources));

    parent.appendChild(message);
  }

  function groupClaims(claims) {
    var grouped = {
      facts: [],
      inferences: [],
      recommendations: []
    };
    claims.forEach(function (claim) {
      if (text(claim.status) && text(claim.status) !== "accepted") {
        return;
      }
      var type = text(claim.type);
      if (type === "recommendation" || type === "idea") {
        grouped.recommendations.push(claim);
      } else if (type === "inference") {
        grouped.inferences.push(claim);
      } else if (type === "fact" || type === "synthesis" || !type) {
        grouped.facts.push(claim);
      } else if (type === "uncertainty") {
        grouped.inferences.push(claim);
      }
    });
    return grouped;
  }

  function appendClaimSection(parent, title, claims, kind) {
    if (!claims.length) {
      return;
    }
    parent.appendChild(el("p", "section-title", title));
    var list = el("ul", "claim-list");
    claims.forEach(function (claim) {
      var item = el("li", "claim " + kind);
      item.appendChild(el("p", "", text(claim.text)));
      var citations = array(claim.citations);
      if (citations.length) {
        item.appendChild(el("p", "claim-cites", citationText(citations)));
      }
      list.appendChild(item);
    });
    parent.appendChild(list);
  }

  function appendRecommendationSection(parent, claims) {
    if (!claims.length) {
      return;
    }
    var box = el("section", "recommendation");
    box.appendChild(el("p", "section-title", "GANG recommendation"));
    box.appendChild(el("p", "note", "Generated from the cited evidence; not a recorded company decision."));
    var list = el("ul", "claim-list");
    claims.forEach(function (claim) {
      var item = el("li", "claim recommendation-claim");
      item.appendChild(el("p", "", text(claim.text)));
      list.appendChild(item);
    });
    box.appendChild(list);
    parent.appendChild(box);
  }

  function appendStatusBlock(parent, result) {
    var values = [];
    if (result.insufficient_evidence) {
      values.push({ text: "Insufficient evidence to answer fully.", className: "insufficient" });
    }
    /* `uncertainties` already opens with the answer's own `uncertainty`, so
       the scalar is only a fallback for results that predate the list.
       Rendering both printed the no-evidence sentence twice. */
    if (Array.isArray(result.uncertainties)) {
      result.uncertainties.forEach(function (item) {
        values.push({ text: item, className: "" });
      });
    } else if (text(result.uncertainty)) {
      values.push({ text: result.uncertainty, className: "" });
    }
    array(result.conflicts).forEach(function (conflict) {
      values.push({ text: text(conflict.summary), className: "" });
    });
    var seen = {};
    values = values.filter(function (value) {
      var key = text(value.text);
      if (!key || Object.prototype.hasOwnProperty.call(seen, key)) {
        return false;
      }
      seen[key] = true;
      return true;
    });
    if (!values.length) {
      return;
    }
    var block = el("section", "status-block");
    block.appendChild(el("p", "section-title", "Uncertainty"));
    var list = el("ul", "status-list");
    values.forEach(function (value) {
      list.appendChild(el("li", value.className, value.text));
    });
    block.appendChild(list);
    parent.appendChild(block);
  }

  function appendSources(parent, sources) {
    if (!sources.length) {
      return;
    }
    parent.appendChild(el("p", "section-title", "Sources"));
    var list = el("ol", "source-list");
    sources.forEach(function (source) {
      var item = el("li");
      var number = text(source.citation_id || source.number || "");
      var title = text(source.title || source.label || source.document_id || "Untitled source");
      var heading = el("span", "source-title");
      if (number) {
        appendText(heading, "[" + number + "] ");
      }
      appendText(heading, title);
      item.appendChild(heading);

      var meta = [];
      if (source.source_type) {
        meta.push(text(source.source_type));
      }
      if (source.updated) {
        meta.push("updated " + text(source.updated));
      }
      if (meta.length) {
        item.appendChild(el("span", "source-meta", meta.join(" · ")));
      }
      list.appendChild(item);
    });
    parent.appendChild(list);
  }

  function citationText(citations) {
    return citations.map(function (value) {
      return "[" + text(value) + "]";
    }).join(" ");
  }

  function modeLabel(mode) {
    return mode === "advisory" ? "Advisory" : "Evidence";
  }

  function scrollThread() {
    nodes.thread.scrollTop = nodes.thread.scrollHeight;
  }

  window.GangAskTesting = {
    buildAskPayload: buildAskPayload,
    groupClaims: groupClaims,
    renderAssistantResult: renderAssistantResult,
    citationText: citationText,
    statusLabel: function (status) {
      if (status === "queued") {
        return "Waiting...";
      }
      if (status === "running") {
        return "Thinking...";
      }
      return "";
    },
    tokenKey: TOKEN_KEY
  };

  document.addEventListener("DOMContentLoaded", boot);
}());
