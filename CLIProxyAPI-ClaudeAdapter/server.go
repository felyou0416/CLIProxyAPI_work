package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type Server struct {
	config     Config
	transport  *Transport
	inflightMu sync.Mutex
	inflight   map[string]*inflightCall
	recentMu   sync.Mutex
	recent     map[string]cachedResult
}

// inflightCall represents an upstream request currently being processed.
// Duplicate calls sharing the same dedup key wait on done and reuse result.
type inflightCall struct {
	done   chan struct{}
	result cachedResult
}

// cachedResult stores a completed response for near-immediate dedup.
// Stream SUCCESSES cannot be replayed (body is nil); stream ERRORS are captured
// as a synthetic error body so repeat 5xx/4xx retries on the same dedup key
// get the exact same error without hammering upstream again.
type cachedResult struct {
	status      int
	ct          string // Content-Type
	xrid        string // X-Request-ID
	body        []byte // set for: non-stream (any status), stream errors
	isStream    bool
	streamOK    bool // true only when stream completed successfully (cannot be replayed)
	errMsg      string // non-empty means call failed
	dedupReason string // "inflight" / "recent-success" / "recent-error"
}

const (
	recentResultTTL        = 30 * time.Second
	recentErrorResultTTL   = 8 * time.Second // shorter window for errors to avoid sticky failures
)

// Stdout-style access logger (mirrors processes.py:CLAUDE_ADAPTER_STDOUT).
// Errors already go through `log` (stderr). Access log here lets operators
// confirm every request that arrived at the adapter, its dedup outcome, and
// what the upstream outcome was — instead of a silent stdout.
var accessLog = log.New(os.Stdout, "", log.LstdFlags)

func NewServer(config Config, transport *Transport) (*Server, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	if transport == nil {
		return nil, fmt.Errorf("transport is required")
	}
	return &Server{
		config:    config,
		transport: transport,
		inflight:  make(map[string]*inflightCall),
		recent:    make(map[string]cachedResult),
	}, nil
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.handleHealth)
	mux.HandleFunc("/v1/messages", s.handleMessages)
	mux.HandleFunc("/v1/messages/count_tokens", s.handleCountTokens)
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		start := time.Now()
		requestID := requestID(req)
		w.Header().Set("x-request-id", requestID)
		lw := &loggingResponseWriter{inner: w, status: 200}
		mux.ServeHTTP(lw, req)
		method := req.Method
		path := req.URL.EscapedPath()
		// Log every request received by the adapter so we can confirm Claude Code
		// traffic actually passes through this layer. 4-5 tokens per entry is
		// enough to eyeball duplicates and dedup hits.
		took := time.Since(start)
		extra := ""
		if v, ok := lw.headerGets("x-dedup-outcome"); ok && v != "" {
			extra = " dedup=" + v
		}
		if model, ok := lw.headerGets("x-requested-model"); ok && model != "" {
			extra += " model=" + model
		}
		accessLog.Printf("%s %s status=%d took=%s%s", method, path, lw.status, took.Round(time.Millisecond), extra)
	})
}

// loggingResponseWriter records the HTTP status for request logging and offers
// a tiny scratchpad of "extra" keys (via standard response headers) that the
// access logger will surface, without propagating them to the actual client
// wire: we strip them here via WriteHeader override.
//
// IMPORTANT: this wrapper MUST forward all optional interfaces the inner
// ResponseWriter may implement (http.Flusher, http.Hijacker, io.ReaderFrom,
// *http.Pusher, etc). If we miss forwarding any of them, callers doing the
// usual `if f, ok := w.(http.Flusher); ok { ... }` will take the "not ok"
// branch and bail — which is exactly how the "streaming is unavailable" 500
// reproduced in T1c. We implement just the interfaces needed by this repo:
// Flusher is required for SSE; Hijacker would be required for WebSocket but
// nothing here uses WS, yet we still forward it defensively.
type loggingResponseWriter struct {
	inner http.ResponseWriter
	status      int
	wroteHeader bool
	scratch     map[string]string
}

// Unwrap lets callers that already know about the wrapper reach the inner
// writer. It also enables future Go 1.20+ http.ResponseController to find
// Flusher/Hijacker implementations — we keep explicit forwarding below so
// older Go versions still work.
func (lw *loggingResponseWriter) Unwrap() http.ResponseWriter { return lw.inner }

// Header delegates to the inner writer; nothing private stored here.
func (lw *loggingResponseWriter) Header() http.Header { return lw.inner.Header() }

func (lw *loggingResponseWriter) WriteHeader(code int) {
	if lw.wroteHeader {
		return
	}
	lw.wroteHeader = true
	lw.status = code
	// Drop private scratch headers so they never reach the client.
	if lw.scratch != nil {
		for k := range lw.scratch {
			lw.inner.Header().Del(k)
		}
	}
	lw.inner.WriteHeader(code)
}

func (lw *loggingResponseWriter) Write(b []byte) (int, error) {
	if !lw.wroteHeader {
		lw.WriteHeader(http.StatusOK)
	}
	return lw.inner.Write(b)
}

// Flush implements http.Flusher, which SSE streaming requires.
// Net/http ResponseWriter always satisfies Flusher since Go 1.0 (when
// writing to an actual net.Conn), so forwarding is safe.
func (lw *loggingResponseWriter) Flush() {
	if !lw.wroteHeader {
		lw.WriteHeader(http.StatusOK)
	}
	if f, ok := lw.inner.(http.Flusher); ok {
		f.Flush()
	}
}

// Hijack implements http.Hijacker (WebSocket or legacy CONNECT tunneling).
// Not used by this adapter today, but forward it defensively so future
// upgrades or proxied handlers don't silently lose hijack support.
func (lw *loggingResponseWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	if hj, ok := lw.inner.(http.Hijacker); ok {
		return hj.Hijack()
	}
	return nil, nil, fmt.Errorf("hijacking is unavailable")
}

func (lw *loggingResponseWriter) setScratch(key, value string) {
	if lw.scratch == nil {
		lw.scratch = make(map[string]string)
	}
	lw.scratch[key] = value
	// Also write to response header *before* WriteHeader; WriteHeader strips.
	lw.inner.Header().Set(key, value)
}

func (lw *loggingResponseWriter) headerGets(key string) (string, bool) {
	if lw.scratch != nil {
		if v, ok := lw.scratch[key]; ok {
			return v, true
		}
	}
	return lw.inner.Header().Get(key), true
}

func noteDedupOutcome(w http.ResponseWriter, reason string) {
	if lw, ok := w.(*loggingResponseWriter); ok {
		lw.setScratch("x-dedup-outcome", reason)
	}
}

func noteRequestedModel(w http.ResponseWriter, model string) {
	if lw, ok := w.(*loggingResponseWriter); ok {
		lw.setScratch("x-requested-model", model)
	}
}

// synthesizeErrorBody builds a small Claude-format error payload that we can
// safely cache & replay to retries of a failing upstream call. Mirrors the
// on-the-wire layout of writeClaudeError so waiters/recent-cache hits get the
// exact same shape as the failing leader.
func synthesizeErrorBody(r cachedResult) []byte {
	if len(r.body) > 0 {
		return r.body
	}
	payload := ClaudeErrorResponse{
		Type:  "error",
		Error: ClaudeError{Type: claudeErrorType(r.status), Message: r.errMsg},
	}
	if payload.Error.Message == "" {
		payload.Error.Message = http.StatusText(r.status)
	}
	if payload.RequestID == "" {
		payload.RequestID = r.xrid
	}
	if payload.RequestID == "" {
		payload.RequestID = "msg_unknown"
	}
	b, _ := json.Marshal(payload)
	return b
}

func (s *Server) handleHealth(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodGet {
		writeClaudeError(w, http.StatusMethodNotAllowed, requestID(req), fmt.Errorf("method not allowed"))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok", "estimator_version": estimatorVersion})
}

func (s *Server) handleCountTokens(w http.ResponseWriter, req *http.Request) {
	id := requestID(req)
	if req.Method != http.MethodPost {
		writeClaudeError(w, http.StatusMethodNotAllowed, id, fmt.Errorf("method not allowed"))
		return
	}
	if !s.authenticate(req) {
		writeClaudeError(w, http.StatusUnauthorized, id, fmt.Errorf("invalid client credentials"))
		return
	}
	body, err := readRequestBody(w, req, s.config.MaxBodyBytes)
	if err != nil {
		writeClaudeError(w, errorStatus(err), id, err)
		return
	}
	var message MessageRequest
	if err := decodeJSON(body, &message); err != nil {
		writeClaudeError(w, http.StatusBadRequest, id, fieldErrorMessage(err))
		return
	}
	if strings.TrimSpace(message.Model) == "" {
		writeClaudeError(w, http.StatusBadRequest, id, fieldError("model", "is required"))
		return
	}
	if _, ok := s.config.RouteFor(message.Model); !ok {
		writeClaudeError(w, http.StatusBadRequest, id, fieldError("model", "is not configured"))
		return
	}
	if err := validateCountRequest(message); err != nil {
		writeClaudeError(w, http.StatusBadRequest, id, fieldErrorMessage(err))
		return
	}
	w.Header().Set("x-model", message.Model)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"input_tokens": EstimateInputTokens(message)})
}

func (s *Server) handleMessages(w http.ResponseWriter, req *http.Request) {
	id := requestID(req)
	if req.Method != http.MethodPost {
		writeClaudeError(w, http.StatusMethodNotAllowed, id, fmt.Errorf("method not allowed"))
		return
	}

	// Step 0: read body UP FRONT.  We need its bytes for (a) JSON parsing,
	// (b) dedup key hash (when client omits x-request-id), and crucially
	// (c) error-cache writes for responses that fail BEFORE we ever reach
	// the executeUpstream codepath (auth failures, unknown model, bad JSON,
	// body too large, ...).  Before this fix these "pre-upstream errors"
	// fell through releaseInflight without a cachedResult and the second
	// identical retry hammered the exact same short-circuit branch again.
	body, bodyErr := readRequestBody(w, req, s.config.MaxBodyBytes)

	// Step 1: extract a requested-model hint (for access logs) from either
	// already-parseable body or, on failure, leave empty. We do this even
	// if authenticate() / the body read are about to fail, because the log
	// line is still useful.
	var modelHint string
	if bodyErr == nil {
		var probe struct {
			Model string `json:"model"`
		}
		_ = decodeJSON(body, &probe)
		modelHint = strings.TrimSpace(probe.Model)
	}
	noteRequestedModel(w, modelHint)

	// Step 2: pick a dedup key. When x-request-id is missing we fall back
	// to a body hash, which is exactly what we need for pre-upstream error
	// dedup to actually work (auth / validation error retries carry the
	// same byte body so the hash matches).
	var key string
	if bodyErr == nil {
		key = dedupKey(req, body)
	} else {
		// Body read failed (too large, client disconnect mid-stream, ...).
		// Use x-request-id only; if that's empty too skip dedup entirely.
		hdrID := strings.TrimSpace(req.Header.Get("x-request-id"))
		if hdrID == "" {
			// No dedup possible; fall through without caching so any
			// subsequent fixable request isn't blocked by a poisoned key.
			key = ""
		} else {
			key = "r:" + hdrID
		}
	}

	// Step 3: recent-error cache hit (covers pre-upstream errors now).
	if key != "" {
		if cached, ok := s.getRecent(key); ok {
			if cached.errMsg != "" {
				noteDedupOutcome(w, "recent-error")
			} else if cached.streamOK {
				noteDedupOutcome(w, "recent-stream-ok(no-replay)")
			} else {
				noteDedupOutcome(w, "recent-success")
			}
			sendCachedResult(w, cached, id, s.transport.apiKey)
			return
		}
	}

	// Step 4: in-flight guard.
	// We open the inflight slot early (before auth/parse) so pre-upstream
	// errors serialize exactly one leader too; waiters of a 401 leader get
	// the exact same cached 401 payload without going through auth again.
	var call *inflightCall
	if key != "" {
		var isWaiter bool
		call, isWaiter = s.acquireInflight(key)
		if isWaiter {
			noteDedupOutcome(w, "inflight-waiter")
			s.waitOnInflight(w, req, call, id)
			return
		}
		noteDedupOutcome(w, "leader")
	}

	// Helper used by every short-circuit branch below: emit the error to
	// the client and, if we own the inflight slot, write a cached error
	// into it so the slot broadcasts + TTL-cache protects retries.
	terminateWithError := func(status int, msg string) {
		r := cachedResult{status: status, errMsg: msg, xrid: id}
		r.body = synthesizeErrorBody(r)
		writeClaudeError(w, status, id, fmt.Errorf("%s", msg), s.transport.apiKey)
		if key != "" && call != nil {
			s.releaseInflight(key, call, r)
		}
	}

	// Step 5: auth.
	if !s.authenticate(req) {
		terminateWithError(http.StatusUnauthorized, "invalid client credentials")
		return
	}

	// Step 6: body read / JSON decode / route lookup.
	if bodyErr != nil {
		terminateWithError(errorStatus(bodyErr), bodyErr.Error())
		return
	}
	var message MessageRequest
	if err := decodeJSON(body, &message); err != nil {
		terminateWithError(http.StatusBadRequest, fieldErrorMessage(err).Error())
		return
	}
	route, ok := s.config.RouteFor(message.Model)
	if !ok {
		terminateWithError(http.StatusBadRequest, fieldError("model", "is not configured").Error())
		return
	}
	chat, err := TranslateRequest(message, route, s.config)
	if err != nil {
		terminateWithError(http.StatusBadRequest, fieldErrorMessage(err).Error())
		return
	}
	if chat.Stream && !s.config.Features.Streaming {
		terminateWithError(http.StatusBadRequest, fieldError("stream", "streaming is disabled").Error())
		return
	}

	// Step 7: happy path -> execute upstream. releaseInflight handles
	// success/error caching and slot cleanup.
	result := s.executeUpstream(w, req, chat, id)
	if key != "" && call != nil {
		s.releaseInflight(key, call, result)
	}
}

// executeUpstream performs the actual upstream call and writes the response.
// Returns a captured cachedResult describing the outcome so dedup waiters can reuse it.
func (s *Server) executeUpstream(w http.ResponseWriter, req *http.Request, chat ChatRequest, id string) cachedResult {
	ctx := req.Context()
	timeout := time.Duration(s.config.Upstream.RequestTimeoutSeconds) * time.Second
	response, err := s.transport.DoWithID(ctx, chat, timeout, id)
	if err != nil {
		if req.Context().Err() != nil {
			return cachedResult{status: 499, isStream: chat.Stream, errMsg: "client canceled"}
		}
		status := upstreamReadStatus(err)
		writeClaudeError(w, status, id, err, s.transport.apiKey)
		r := cachedResult{status: status, isStream: chat.Stream, errMsg: err.Error(), xrid: id}
		r.body = synthesizeErrorBody(r)
		return r
	}
	defer response.Body.Close()
	xrid := response.Header.Get("x-request-id")
	if xrid == "" {
		xrid = id
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		raw, readErr := readLimited(response.Body, s.config.MaxBodyBytes)
		if readErr != nil {
			writeClaudeError(w, upstreamReadStatus(readErr), xrid, fmt.Errorf("read upstream error response: %w", readErr), s.transport.apiKey)
			r := cachedResult{status: upstreamReadStatus(readErr), isStream: chat.Stream, errMsg: readErr.Error(), xrid: xrid}
			r.body = synthesizeErrorBody(r)
			return r
		}
		upErr := upstreamErrorFromBody(response.StatusCode, raw, xrid)
		writeClaudeError(w, response.StatusCode, xrid, upErr, s.transport.apiKey)
		r := cachedResult{status: response.StatusCode, isStream: chat.Stream, errMsg: upErr.Error(), xrid: xrid}
		r.body = synthesizeErrorBody(r)
		return r
	}
	if chat.Stream {
		// Stream: write to live client; capture errors into body so waiters can replay.
		// Successful stream results are not replayable (marked with streamOK).
		converter := s.runStreamConverter(w, response.Body, req.Context(), xrid, chat.Model)
		if converter != nil && converter.lastStreamErr != nil {
			status := http.StatusBadGateway
			if converter.lastStreamStatus != 0 {
				status = converter.lastStreamStatus
			}
			r := cachedResult{status: status, isStream: true, errMsg: converter.lastStreamErr.Error(), xrid: xrid}
			r.body = synthesizeErrorBody(r)
			return r
		}
		return cachedResult{status: http.StatusOK, isStream: true, streamOK: true, xrid: xrid, ct: "text/event-stream"}
	}
	raw, err := readLimited(response.Body, s.config.MaxBodyBytes)
	if err != nil {
		if req.Context().Err() != nil {
			return cachedResult{status: 499, isStream: false, errMsg: "client canceled", xrid: xrid}
		}
		status := upstreamReadStatus(err)
		writeClaudeError(w, status, xrid, err, s.transport.apiKey)
		r := cachedResult{status: status, isStream: false, errMsg: err.Error(), xrid: xrid}
		r.body = synthesizeErrorBody(r)
		return r
	}
	translated, err := TranslateResponse(raw, response.StatusCode, xrid)
	if err != nil {
		writeClaudeError(w, http.StatusBadGateway, xrid, err, s.transport.apiKey)
		r := cachedResult{status: http.StatusBadGateway, isStream: false, errMsg: err.Error(), xrid: xrid}
		r.body = synthesizeErrorBody(r)
		return r
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("x-request-id", xrid)
	encoded, encErr := json.Marshal(translated)
	if encErr != nil {
		// Fallback: encode inline
		_ = json.NewEncoder(w).Encode(translated)
		// Inline encoding = cannot safely replay as exact bytes, but success
		// message = still mark as success so waiters get 409, not an error.
		return cachedResult{status: http.StatusOK, isStream: false, streamOK: false, xrid: xrid, ct: "application/json", errMsg: encErr.Error()}
	}
	_, _ = w.Write(encoded)
	return cachedResult{
		status:   http.StatusOK,
		ct:       "application/json",
		xrid:     xrid,
		body:     append([]byte(nil), encoded...),
		isStream: false,
	}
}

// runStreamConverter wraps the SSE stream loop in a helper so we can
// capture mid-stream errors (timeouts, protocol errors, bad upstream bytes)
// back out into a cachedResult that dedup waiters / the recent-error cache can
// replay instead of sending the same failing request upstream again.
func (s *Server) runStreamConverter(w http.ResponseWriter, body io.Reader, ctx context.Context, id, model string) *SSEConverter {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeClaudeError(w, http.StatusInternalServerError, id, fmt.Errorf("streaming is unavailable"))
		return nil
	}
	flusher.Flush()
	converter := NewSSEConverter(w, flusher, id, model, s.transport.apiKey)
	limited := &countingReader{reader: io.LimitReader(body, s.config.MaxBodyBytes+1)}
	scanner := bufio.NewScanner(limited)
	scanner.Buffer(make([]byte, 4096), 8<<20)
	seenDone := false
	for scanner.Scan() {
		if ctx.Err() != nil {
			// Client disconnect: not an upstream failure we should cache.
			converter.lastStreamErr = nil
			return converter
		}
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "data:") {
			data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if data == "[DONE]" {
				seenDone = true
				continue
			}
			if err := converter.HandleData(data); err != nil {
				if ctx.Err() == nil {
					converter.EmitError(err)
					converter.lastStreamErr = err
				}
				return converter
			}
		}
	}
	if ctx.Err() != nil {
		converter.lastStreamErr = nil
		return converter
	}
	if err := scanner.Err(); err != nil {
		if limited.bytes > s.config.MaxBodyBytes {
			converter.EmitError(bodyLimitError{limit: s.config.MaxBodyBytes})
			converter.lastStreamErr = bodyLimitError{limit: s.config.MaxBodyBytes}
			return converter
		}
		converter.EmitError(streamError(err, id))
		converter.lastStreamErr = streamError(err, id)
		return converter
	}
	if limited.bytes > s.config.MaxBodyBytes {
		converter.EmitError(bodyLimitError{limit: s.config.MaxBodyBytes})
		converter.lastStreamErr = bodyLimitError{limit: s.config.MaxBodyBytes}
		return converter
	}
	if !converter.closed {
		converter.Close()
	}
	_ = seenDone
	return converter
}

// waitOnInflight blocks until the in-flight leader completes, then serves the shared result.
func (s *Server) waitOnInflight(w http.ResponseWriter, req *http.Request, call *inflightCall, id string) {
	select {
	case <-call.done:
		sendCachedResult(w, call.result, id, s.transport.apiKey)
	case <-req.Context().Done():
		// Waiter gave up; leader continues unaffected.
	}
}

// sendCachedResult replays a captured dedup result back to a waiter / recent-cache hit.
func sendCachedResult(w http.ResponseWriter, r cachedResult, fallbackID string, secrets ...string) {
	xrid := r.xrid
	if xrid == "" {
		xrid = fallbackID
	}
	if r.errMsg != "" {
		// Replay the cached error body verbatim if we captured one, otherwise
		// fall back to a fresh writeClaudeError so the wire shape still matches
		// what the leader emitted.
		if len(r.body) > 0 {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("x-request-id", xrid)
			w.WriteHeader(r.status)
			_, _ = w.Write(r.body)
			return
		}
		writeClaudeError(w, r.status, xrid, fmt.Errorf("%s", r.errMsg), secrets...)
		return
	}
	if r.isStream {
		// Cannot replay an SSE byte stream; tell client this id already delivered.
		writeClaudeError(w, http.StatusConflict, xrid, fmt.Errorf("duplicate x-request-id: original stream completed successfully; if retrying please send a new x-request-id"), secrets...)
		return
	}
	if r.ct != "" {
		w.Header().Set("Content-Type", r.ct)
	}
	w.Header().Set("x-request-id", xrid)
	w.WriteHeader(r.status)
	if len(r.body) > 0 {
		_, _ = w.Write(r.body)
	}
}

type countingReader struct {
	reader io.Reader
	bytes  int64
}

func (r *countingReader) Read(p []byte) (int, error) {
	n, err := r.reader.Read(p)
	r.bytes += int64(n)
	return n, err
}

func (s *Server) authenticate(req *http.Request) bool {
	provided := strings.TrimSpace(req.Header.Get("x-api-key"))
	if provided == "" {
		auth := strings.TrimSpace(req.Header.Get("Authorization"))
		if len(auth) >= 7 && strings.EqualFold(auth[:7], "bearer ") {
			provided = strings.TrimSpace(auth[7:])
		}
	}
	for _, key := range s.config.ClientAuth.APIKeys {
		if subtle.ConstantTimeCompare([]byte(provided), []byte(key)) == 1 {
			return true
		}
	}
	return false
}

func readRequestBody(w http.ResponseWriter, req *http.Request, limit int64) ([]byte, error) {
	if req.Body == nil {
		return nil, fmt.Errorf("request body is required")
	}
	limited := http.MaxBytesReader(w, req.Body, limit)
	raw, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, fmt.Errorf("request body exceeds %d bytes", limit)
	}
	return raw, nil
}

func decodeJSON(raw []byte, target any) error {
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return fmt.Errorf("request body must contain one JSON value")
	}
	return nil
}

func validateCountRequest(req MessageRequest) error {
	if req.MaxTokens < 0 {
		return fieldError("max_tokens", "cannot be negative")
	}
	if len(req.Messages) == 0 && len(req.Tools) == 0 && !hasJSONValue(req.System) {
		return fieldError("messages", "must contain at least one message, tool, or system prompt")
	}
	return nil
}

func errorStatus(err error) int {
	var maxBytesError *http.MaxBytesError
	if errors.As(err, &maxBytesError) {
		return http.StatusRequestEntityTooLarge
	}
	if isTimeoutError(err) {
		return http.StatusGatewayTimeout
	}
	return http.StatusBadRequest
}

func streamError(err error, requestID string) error {
	if isTimeoutError(err) {
		return upstreamAPIError(http.StatusGatewayTimeout, "upstream request timed out", requestID)
	}
	return err
}

func upstreamReadStatus(err error) int {
	if isTimeoutError(err) {
		return http.StatusGatewayTimeout
	}
	return http.StatusBadGateway
}

func isTimeoutError(err error) bool {
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}
	var timeoutError interface{ Timeout() bool }
	return errors.As(err, &timeoutError) && timeoutError.Timeout()
}

func requestID(req *http.Request) string {
	if value := strings.TrimSpace(req.Header.Get("x-request-id")); value != "" {
		return value
	}
	var bytes [12]byte
	if _, err := rand.Read(bytes[:]); err == nil {
		return "msg_" + hex.EncodeToString(bytes[:])
	}
	return "msg_unknown"
}

func upstreamErrorFromBody(status int, raw []byte, id string) error {
	var response ChatResponse
	if json.Unmarshal(raw, &response) == nil && response.Error != nil {
		return upstreamAPIError(status, response.Error.Message, id)
	}
	message := strings.TrimSpace(string(raw))
	if message == "" {
		message = http.StatusText(status)
	}
	return upstreamAPIError(status, message, id)
}

// dedupKey returns the deduplication key for a request.
// Primary key = explicit X-Request-ID set by the client (Claude Code).
// Fallback = sha256(body) truncated to 32 base64 chars to avoid unbounded keys.
func dedupKey(req *http.Request, body []byte) string {
	if value := strings.TrimSpace(req.Header.Get("x-request-id")); value != "" {
		return "rid:" + value
	}
	authTag := strings.TrimSpace(req.Header.Get("Authorization")) + "|" + strings.TrimSpace(req.Header.Get("x-api-key"))
	sum := sha256.Sum256(append([]byte(authTag+":"), body...))
	return "h:" + base64.RawURLEncoding.EncodeToString(sum[:])
}

// acquireInflight either reserves a new in-flight slot (returns call,nil) or
// returns the already-inflight entry together with isWaiter=true.
func (s *Server) acquireInflight(key string) (call *inflightCall, isWaiter bool) {
	s.inflightMu.Lock()
	defer s.inflightMu.Unlock()
	if existing, ok := s.inflight[key]; ok {
		return existing, true
	}
	call = &inflightCall{done: make(chan struct{})}
	s.inflight[key] = call
	return call, false
}

// releaseInflight removes the in-flight entry and stores a short-TTL cached
// result. Caching policy:
//   - SUCCESS non-stream, with body => cache for 30s (full replay).
//   - SUCCESS stream (streamOK) => do NOT cache (body cannot be replayed;
//     409 on retries is acceptable but only for truly-inflight waiters;
//     caching a "409-forever" across TTL would hide legitimate next calls).
//   - ERRORS (any combination of isStream/non-stream) => cache for 8s.
//     Errors are synthesized into a Claude-format error payload so retries
//     of the same failing fingerprint return the same error without issuing
//     another upstream round-trip — this is the big hammer for repeated
//     429/503/502 cascades seen in the 09-03 request archive.
func (s *Server) releaseInflight(key string, call *inflightCall, result cachedResult) {
	s.inflightMu.Lock()
	delete(s.inflight, key)
	s.inflightMu.Unlock()
	call.result = result
	close(call.done)

	isError := result.errMsg != ""
	shouldCache := false
	var ttl time.Duration
	switch {
	case isError:
		// Cache errors (stream + non-stream). 499 = client-canceled is not
		// an upstream failure. 401 = invalid credentials should not be cached
		// to avoid locking out subsequent retries with valid credentials.
		if result.status != 499 && result.status != http.StatusUnauthorized {
			shouldCache = true
			ttl = recentErrorResultTTL
		}
	case result.streamOK:
		// Stream success: bytes already flushed; cannot replay.
		shouldCache = false
	case !result.isStream && result.body != nil:
		shouldCache = true
		ttl = recentResultTTL
	}
	if shouldCache {
		s.recentMu.Lock()
		s.recent[key] = result
		s.recentMu.Unlock()
		// Evict lazily after TTL.
		time.AfterFunc(ttl, func() {
			s.recentMu.Lock()
			delete(s.recent, key)
			s.recentMu.Unlock()
		})
	}
}

// getRecent returns a cached recent-completed result if any.
func (s *Server) getRecent(key string) (cachedResult, bool) {
	s.recentMu.Lock()
	defer s.recentMu.Unlock()
	v, ok := s.recent[key]
	return v, ok
}
