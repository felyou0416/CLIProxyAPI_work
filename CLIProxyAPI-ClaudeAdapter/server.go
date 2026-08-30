package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Server struct {
	config    Config
	transport *Transport
}

func NewServer(config Config, transport *Transport) (*Server, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	if transport == nil {
		return nil, fmt.Errorf("transport is required")
	}
	return &Server{config: config, transport: transport}, nil
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.handleHealth)
	mux.HandleFunc("/v1/messages", s.handleMessages)
	mux.HandleFunc("/v1/messages/count_tokens", s.handleCountTokens)
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requestID := requestID(req)
		w.Header().Set("x-request-id", requestID)
		mux.ServeHTTP(w, req)
	})
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
	if _, ok := s.config.RouteFor(message.Model); !ok {
		writeClaudeError(w, http.StatusBadRequest, id, fieldError("model", "is not configured"))
		return
	}
	if err := validateCountRequest(message); err != nil {
		writeClaudeError(w, http.StatusBadRequest, id, fieldErrorMessage(err))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"input_tokens": EstimateInputTokens(message)})
}

func (s *Server) handleMessages(w http.ResponseWriter, req *http.Request) {
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
	route, ok := s.config.RouteFor(message.Model)
	if !ok {
		writeClaudeError(w, http.StatusBadRequest, id, fieldError("model", "is not configured"))
		return
	}
	chat, err := TranslateRequest(message, route, s.config)
	if err != nil {
		writeClaudeError(w, http.StatusBadRequest, id, fieldErrorMessage(err))
		return
	}
	if chat.Stream && !s.config.Features.Streaming {
		writeClaudeError(w, http.StatusBadRequest, id, fieldError("stream", "streaming is disabled"))
		return
	}
	ctx := req.Context()
	response, err := s.transport.Do(ctx, chat, time.Duration(s.config.Upstream.RequestTimeoutSeconds)*time.Second)
	if err != nil {
		// The client owns the response lifecycle after cancellation; writing an
		// error here would race with the closed connection and add noise.
		if req.Context().Err() != nil {
			return
		}
		writeClaudeError(w, upstreamReadStatus(err), id, err, s.transport.apiKey)
		return
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		raw, readErr := readLimited(response.Body, s.config.MaxBodyBytes)
		requestIDValue := response.Header.Get("x-request-id")
		if requestIDValue == "" {
			requestIDValue = id
		}
		if readErr != nil {
			writeClaudeError(w, upstreamReadStatus(readErr), requestIDValue, fmt.Errorf("read upstream error response: %w", readErr), s.transport.apiKey)
			return
		}
		writeClaudeError(w, response.StatusCode, requestIDValue, upstreamErrorFromBody(response.StatusCode, raw, requestIDValue), s.transport.apiKey)
		return
	}
	if chat.Stream {
		s.streamResponse(w, response.Body, req.Context(), id, chat.Model)
		return
	}
	raw, err := readLimited(response.Body, s.config.MaxBodyBytes)
	if err != nil {
		if req.Context().Err() != nil {
			return
		}
		writeClaudeError(w, upstreamReadStatus(err), id, err, s.transport.apiKey)
		return
	}
	translated, err := TranslateResponse(raw, response.StatusCode, id)
	if err != nil {
		writeClaudeError(w, http.StatusBadGateway, id, err, s.transport.apiKey)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(translated)
}

func (s *Server) streamResponse(w http.ResponseWriter, body io.Reader, ctx context.Context, id, model string) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeClaudeError(w, http.StatusInternalServerError, id, fmt.Errorf("streaming is unavailable"))
		return
	}
	converter := NewSSEConverter(w, flusher, id, model, s.transport.apiKey)
	limited := &countingReader{reader: io.LimitReader(body, s.config.MaxBodyBytes+1)}
	scanner := bufio.NewScanner(limited)
	scanner.Buffer(make([]byte, 4096), 8<<20)
	for scanner.Scan() {
		if ctx.Err() != nil {
			return
		}
		line := scanner.Text()
		if strings.HasPrefix(line, "data:") {
			if err := converter.HandleData(strings.TrimSpace(strings.TrimPrefix(line, "data:"))); err != nil {
				if ctx.Err() == nil {
					converter.EmitError(err)
				}
				return
			}
		}
	}
	if ctx.Err() != nil {
		return
	}
	if err := scanner.Err(); err != nil {
		if limited.bytes > s.config.MaxBodyBytes {
			converter.EmitError(bodyLimitError{limit: s.config.MaxBodyBytes})
			return
		}
		converter.EmitError(streamError(err, id))
		return
	}
	if ctx.Err() != nil {
		return
	}
	if limited.bytes > s.config.MaxBodyBytes {
		converter.EmitError(bodyLimitError{limit: s.config.MaxBodyBytes})
		return
	}
	converter.Close()
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
	if req.MaxTokens <= 0 {
		return fieldError("max_tokens", "must be positive")
	}
	if len(req.Messages) == 0 {
		return fieldError("messages", "must contain at least one message")
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
