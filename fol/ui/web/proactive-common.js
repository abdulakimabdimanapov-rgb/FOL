/* proactive-common.js — pure logic for the proactive suggestion UI (Phase 8).
 *
 * Kept free of DOM so it can be unit-tested with `node --test` and reused by
 * any UI surface (web, SwiftUI wrapper). Exposes:
 *   - normalizeProactiveEvent(raw)  — validate/normalize a WS payload (null on malformed)
 *   - ProactiveState                 — dedupe + lifecycle (show/ignore, dismissed, executed)
 *   - attachSocketHandlers(ws, h)    — single-listener wiring (never duplicates)
 *   - createProactiveSocket(url, h)  — WS with reconnect/backoff, single instance
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ProactiveCommon = api;
})(typeof self !== 'undefined' ? self : globalThis, function () {
  'use strict';

  var DEFAULT_DEDUPE_MS = 60 * 1000;

  /**
   * Validate and normalize a raw WebSocket payload into a suggestion object,
   * or null when the payload is malformed (missing/invalid title). Unknown
   * extra fields are ignored — a malformed event is a safe no-op.
   */
  function normalizeProactiveEvent(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    var title = typeof raw.title === 'string' ? raw.title.trim() : '';
    if (!title) return null;
    var description = typeof raw.description === 'string' ? raw.description : '';
    var action = typeof raw.action === 'string' ? raw.action : '';
    var category = typeof raw.category === 'string' ? raw.category : 'general';
    var priority = (typeof raw.priority === 'number' && isFinite(raw.priority))
      ? raw.priority
      : 0.5;
    var context = (raw.context && typeof raw.context === 'object' && !Array.isArray(raw.context))
      ? raw.context
      : {};
    return {
      title: title,
      description: description,
      action: action,
      category: category,
      priority: priority,
      context: context,
      receivedAt: Date.now(),
    };
  }

  /**
   * Dedupe + lifecycle state for the banner.
   *
   * ingest() returns "show" when the suggestion should be displayed and
   * "ignore" for: exact duplicate events, the same title within the dedupe
   * window, and titles the user already dismissed or executed.
   */
  function ProactiveState(opts) {
    opts = opts || {};
    this.dedupeWindowMs = opts.dedupeWindowMs || DEFAULT_DEDUPE_MS;
    this._current = null;
    this._seen = new Map();     // key|title -> timestamp
    this._dismissed = new Set();
    this._executed = new Set();
  }

  ProactiveState.prototype.ingest = function (suggestion) {
    if (!suggestion) return 'ignore';
    var now = Date.now();
    var eventKey = suggestion.title + '|' + (suggestion.receivedAt || 0);
    if (this._seen.has(eventKey)) return 'ignore'; // exact duplicate event
    var lastSeen = this._seen.get(suggestion.title);
    if (lastSeen !== undefined && now - lastSeen < this.dedupeWindowMs) return 'ignore';
    if (this._dismissed.has(suggestion.title)) return 'ignore';
    if (this._executed.has(suggestion.title)) return 'ignore';
    this._prune(now);
    this._seen.set(eventKey, now);
    this._seen.set(suggestion.title, now);
    this._current = suggestion;
    return 'show';
  };

  ProactiveState.prototype.markExecuted = function () {
    if (this._current) this._executed.add(this._current.title);
    this._current = null;
  };

  ProactiveState.prototype.markDismissed = function () {
    if (this._current) this._dismissed.add(this._current.title);
    this._current = null;
  };

  ProactiveState.prototype._prune = function (now) {
    var self = this;
    this._seen.forEach(function (t, k) {
      if (now - t > self.dedupeWindowMs) self._seen.delete(k);
    });
  };

  Object.defineProperty(ProactiveState.prototype, 'current', {
    get: function () { return this._current; },
  });

  /**
   * Wire handlers to a ws-like object. Always REPLACES onmessage/onopen/
   * onclose/onerror — a single listener per connection, so reconnects can
   * never stack duplicate handlers.
   */
  function attachSocketHandlers(ws, handlers) {
    var h = handlers || {};
    ws.onopen = function () { if (h.onopen) h.onopen(); };
    ws.onclose = function (e) { if (h.onclose) h.onclose(e); };
    ws.onerror = function (e) { if (h.onerror) h.onerror(e); };
    ws.onmessage = function (evt) {
      if (!h.onMessage) return;
      try {
        var data = (evt && typeof evt.data === 'string') ? evt.data : '';
        h.onMessage(data);
      } catch (err) {
        if (h.onError) h.onError(err);
      }
    };
    return ws;
  }

  /**
   * Create a WebSocket connection with reconnect + exponential backoff.
   * Single-instance guard: calling connect() again while a connection is
   * open/connecting is a no-op. Returns a handle with close()/readyState.
   */
  function createProactiveSocket(url, handlers, opts) {
    opts = opts || {};
    var WSImpl = opts.WebSocketImpl ||
      (typeof WebSocket !== 'undefined' ? WebSocket : null);
    if (!WSImpl) return null;
    var delay = opts.delay || function (attempt) {
      return Math.min(1000 * Math.pow(2, attempt), 15000);
    };
    var maxAttempts = opts.maxAttempts || Infinity;
    var ws = null;
    var closed = false;
    var attempt = 0;

    function connect() {
      if (closed) return;
      if (ws && (ws.readyState === 0 || ws.readyState === 1)) return; // no duplicates
      var next;
      try {
        next = new WSImpl(url);
      } catch (err) {
        if (handlers.onerror) handlers.onerror(err);
        scheduleRetry();
        return;
      }
      ws = attachSocketHandlers(next, {
        onopen: function () {
          attempt = 0;
          if (handlers.onopen) handlers.onopen();
        },
        onclose: function (e) {
          if (handlers.onclose) handlers.onclose(e);
          scheduleRetry();
        },
        onerror: function (e) {
          if (handlers.onerror) handlers.onerror(e);
        },
        onMessage: function (data) {
          if (handlers.onMessage) handlers.onMessage(data);
        },
        onError: function (err) {
          if (handlers.onError) handlers.onError(err);
        },
      });
    }

    function scheduleRetry() {
      if (closed || attempt >= maxAttempts) return;
      attempt += 1;
      setTimeout(connect, delay(attempt));
    }

    connect();
    return {
      close: function () {
        closed = true;
        try { if (ws) ws.close(); } catch (e) { /* noop */ }
      },
      get readyState() {
        return ws ? ws.readyState : -1;
      },
    };
  }

  return {
    normalizeProactiveEvent: normalizeProactiveEvent,
    ProactiveState: ProactiveState,
    attachSocketHandlers: attachSocketHandlers,
    createProactiveSocket: createProactiveSocket,
  };
});
