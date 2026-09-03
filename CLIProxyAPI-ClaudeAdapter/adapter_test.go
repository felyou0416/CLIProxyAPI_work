package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"gopkg.in/yaml.v3"
)

func testConfig(upstreamURL string) Config {
	config := DefaultConfig()
	config.Enabled = true
	config.Upstream.BaseURL = upstreamURL
	config.Upstream.APIKey = "internal-upstream-key"
	config.ClientAuth.APIKeys = []string{"client-key"}
	config.Routes = []Route{{
		Alias:          "claude-test",
		UpstreamModel:  "provider-test",
		UpstreamFormat: "openai-chat-completions",
	}}
	config.MaxBodyBytes = 1024
	return config
}

func newTestServer(t *testing.T, upstreamURL string) *httptest.Server {
	t.Helper()
	config := testConfig(upstreamURL)
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		t.Fatal(err)
	}
	return httptest.NewServer(server.Handler())
}

func messageRequestJSON(t *testing.T, request MessageRequest) []byte {
	t.Helper()
	raw, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func basicMessageRequest() MessageRequest {
	return MessageRequest{
		Model:     "claude-test",
		MaxTokens: 64,
		Messages:  []Message{{Role: "user", Content: json.RawMessage(`"hello"`)}},
	}
}

func TestLoadConfigPreservesDefaultsForOmittedNestedFields(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "adapter.yaml")
	raw := []byte("enabled: true\nclient_auth:\n  api_keys: [client-key]\nroutes:\n  - alias: claude-test\n    upstream_model: provider-test\n")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}

	config, err := LoadConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	if config.Listen.Host != "127.0.0.1" || config.Listen.Port != 8319 {
		t.Fatalf("listen defaults were not preserved: %+v", config.Listen)
	}
	if config.Upstream.BaseURL != "http://127.0.0.1:8317" || config.Upstream.RequestTimeoutSeconds != 600 {
		t.Fatalf("upstream defaults were not preserved: %+v", config.Upstream)
	}
	if !config.Features.Streaming || !config.Features.Tools || !config.Features.Images {
		t.Fatalf("feature defaults were not preserved: %+v", config.Features)
	}
	if config.Features.CountTokens.Mode != "local_estimate" || config.Thinking.Unsupported != "reject" {
		t.Fatalf("policy defaults were not preserved: %+v", config)
	}
}

func TestTranslateRequestSupportsSystemImageToolsAndToolResult(t *testing.T) {
	config := testConfig("http://127.0.0.1:1")
	route, ok := config.RouteFor("models/CLAUDE-TEST")
	if !ok {
		t.Fatal("route was not normalized")
	}
	request := MessageRequest{
		Model:     "models/CLAUDE-TEST",
		MaxTokens: 32,
		System:    json.RawMessage(`"be concise"`),
		Messages: []Message{{
			Role:    "assistant",
			Content: json.RawMessage(`[{"type":"text","text":"call"},{"type":"tool_use","id":"call-1","name":"lookup","input":{"q":"x"}}]`),
		}, {
			Role:    "user",
			Content: json.RawMessage(`[{"type":"tool_result","tool_use_id":"call-1","content":"result"},{"type":"image","source":{"type":"url","url":"https://example.test/image.png"}}]`),
		}},
		Tools: []Tool{{
			Name:        "lookup",
			Description: "Look up a value",
			InputSchema: json.RawMessage(`{"type":"object","properties":{"q":{"type":"string"}}}`),
		}},
		ToolChoice: json.RawMessage(`"any"`),
	}

	translated, err := TranslateRequest(request, route, config)
	if err != nil {
		t.Fatal(err)
	}
	if translated.Model != "claude-test" {
		t.Fatalf("expected alias to be sent through gateway, got %q", translated.Model)
	}
	if len(translated.Messages) != 5 {
		t.Fatalf("expected system, assistant text, tool call, tool result, and image messages; got %d", len(translated.Messages))
	}
	if translated.Messages[0].Role != "system" || string(translated.Messages[0].Content) != `"be concise"` {
		t.Fatalf("unexpected system message: %+v", translated.Messages[0])
	}
	if len(translated.Messages[2].ToolCalls) != 1 || translated.Messages[2].ToolCalls[0].Function.Name != "lookup" {
		t.Fatalf("unexpected tool call message: %+v", translated.Messages[2])
	}
	if translated.Messages[3].Role != "tool" || translated.Messages[3].ToolCallID != "call-1" {
		t.Fatalf("unexpected tool result message: %+v", translated.Messages[3])
	}
	if len(translated.Tools) != 1 || string(translated.ToolChoice) != `"required"` {
		t.Fatalf("unexpected tool translation: %+v", translated)
	}
	if !strings.Contains(string(translated.Messages[3].Content), "result") {
		t.Fatalf("tool result content was lost: %s", translated.Messages[3].Content)
	}
}

func TestTranslateRequestRejectsUnsupportedBlocksAndThinking(t *testing.T) {
	config := testConfig("http://127.0.0.1:1")
	route := config.Routes[0]
	cases := []struct {
		name    string
		request MessageRequest
		field   string
	}{
		{
			name: "document",
			request: MessageRequest{Model: "claude-test", MaxTokens: 1, Messages: []Message{{
				Role: "user", Content: json.RawMessage(`[{"type":"document","source":{}}]`),
			}}},
			field: "document",
		},
		{
			name: "thinking",
			request: MessageRequest{Model: "claude-test", MaxTokens: 1, Thinking: json.RawMessage(`{"type":"enabled"}`), Messages: []Message{{
				Role: "user", Content: json.RawMessage(`"hello"`),
			}}},
			field: "thinking",
		},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			_, err := TranslateRequest(test.request, route, config)
			if err == nil || !strings.Contains(err.Error(), test.field) {
				t.Fatalf("expected %s error, got %v", test.field, err)
			}
		})
	}
}

func TestReadLimitedRejectsOversizedBody(t *testing.T) {
	_, err := readLimited(strings.NewReader("12345"), 4)
	if err == nil {
		t.Fatal("expected body limit error")
	}
	var limitErr bodyLimitError
	if !errorsAs(err, &limitErr) {
		t.Fatalf("expected bodyLimitError, got %T: %v", err, err)
	}
}

func TestServerMessagesAndCountTokensDoNotUseSameUpstreamPath(t *testing.T) {
	var completions atomic.Int32
	var receivedAuthorization atomic.Value
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("unexpected upstream path %q", r.URL.Path)
		}
		completions.Add(1)
		receivedAuthorization.Store(r.Header.Get("Authorization"))
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chat-1","model":"claude-test","choices":[{"index":0,"message":{"role":"assistant","content":"hello from upstream"},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":3}}`)
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()
	request := basicMessageRequest()
	body := messageRequestJSON(t, request)

	countResponse, err := http.Post(adapter.URL+"/v1/messages/count_tokens", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer countResponse.Body.Close()
	if countResponse.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected unauthorized without adapter key, got %d", countResponse.StatusCode)
	}
	if completions.Load() != 0 {
		t.Fatal("unauthorized count request reached upstream")
	}

	countRequest, err := http.NewRequest(http.MethodPost, adapter.URL+"/v1/messages/count_tokens", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	countRequest.Header.Set("x-api-key", "client-key")
	countResponse, err = http.DefaultClient.Do(countRequest)
	if err != nil {
		t.Fatal(err)
	}
	countPayload, err := io.ReadAll(countResponse.Body)
	countResponse.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if countResponse.StatusCode != http.StatusOK {
		t.Fatalf("count_tokens returned %d: %s", countResponse.StatusCode, countPayload)
	}
	var countResult struct {
		InputTokens int `json:"input_tokens"`
	}
	if err := json.Unmarshal(countPayload, &countResult); err != nil {
		t.Fatal(err)
	}
	if countResult.InputTokens <= 0 || completions.Load() != 0 {
		t.Fatalf("count_tokens should estimate locally, result=%+v upstream_calls=%d", countResult, completions.Load())
	}

	messageRequest, err := http.NewRequest(http.MethodPost, adapter.URL+"/v1/messages", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	messageRequest.Header.Set("Authorization", "Bearer client-key")
	messageResponse, err := http.DefaultClient.Do(messageRequest)
	if err != nil {
		t.Fatal(err)
	}
	messagePayload, err := io.ReadAll(messageResponse.Body)
	messageResponse.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if messageResponse.StatusCode != http.StatusOK {
		t.Fatalf("messages returned %d: %s", messageResponse.StatusCode, messagePayload)
	}
	var translated MessageResponse
	if err := json.Unmarshal(messagePayload, &translated); err != nil {
		t.Fatal(err)
	}
	if translated.Content[0].Text != "hello from upstream" || translated.Usage.InputTokens != 7 {
		t.Fatalf("unexpected translated response: %+v", translated)
	}
	if completions.Load() != 1 {
		t.Fatalf("expected one completion request, got %d", completions.Load())
	}
	if got := receivedAuthorization.Load(); got != "Bearer internal-upstream-key" {
		t.Fatalf("unexpected upstream authorization: %v", got)
	}
}

func TestServerMapsAuthenticationBodyLimitAndUpstreamErrors(t *testing.T) {
	var upstreamCalls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamCalls.Add(1)
		w.Header().Set("x-request-id", "upstream-request")
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"type":"rate_limit_error","message":"provider rate limit"}}`)
	}))
	defer upstream.Close()
	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()

	invalidAuth, err := http.Post(adapter.URL+"/v1/messages", "application/json", bytes.NewReader(messageRequestJSON(t, basicMessageRequest())))
	if err != nil {
		t.Fatal(err)
	}
	invalidAuth.Body.Close()
	if invalidAuth.StatusCode != http.StatusUnauthorized || upstreamCalls.Load() != 0 {
		t.Fatalf("invalid auth result=%d upstream_calls=%d", invalidAuth.StatusCode, upstreamCalls.Load())
	}

	config := testConfig(upstream.URL)
	config.MaxBodyBytes = 8
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		t.Fatal(err)
	}
	limitedAdapter := httptest.NewServer(server.Handler())
	defer limitedAdapter.Close()
	oversized, err := http.NewRequest(http.MethodPost, limitedAdapter.URL+"/v1/messages", strings.NewReader(`{"model":"claude-test","messages":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	oversized.Header.Set("x-api-key", "client-key")
	oversizedResponse, err := http.DefaultClient.Do(oversized)
	if err != nil {
		t.Fatal(err)
	}
	oversizedResponse.Body.Close()
	if oversizedResponse.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413 for oversized request, got %d", oversizedResponse.StatusCode)
	}

	request := httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, basicMessageRequest()))
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("expected upstream status to be preserved, got %d: %s", response.StatusCode, payload)
	}
	var errorPayload ClaudeErrorResponse
	if err := json.Unmarshal(payload, &errorPayload); err != nil {
		t.Fatal(err)
	}
	if errorPayload.Error.Type != "rate_limit_error" || errorPayload.RequestID != "upstream-request" {
		t.Fatalf("unexpected error payload: %+v", errorPayload)
	}
}

func httpRequestWithKey(t *testing.T, url string, body []byte) *http.Request {
	t.Helper()
	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("x-api-key", "client-key")
	return request
}

func errorsAs(err error, target *bodyLimitError) bool {
	value, ok := err.(bodyLimitError)
	if ok {
		*target = value
		return true
	}
	return false
}

func TestSSEConverterUsesStableZeroBasedBlockIndexes(t *testing.T) {
	recorder := httptest.NewRecorder()
	converter := NewSSEConverter(recorder, recorder, "request-1", "claude-test")
	data := []string{
		`{"id":"chat-1","model":"claude-test","choices":[{"delta":{"role":"assistant"}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-0","type":"function","function":{"name":"first","arguments":"{\"a\":"}}]}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call-1","type":"function","function":{"name":"second","arguments":"{\"b\":"}}]}}]}`,
		`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]}}]}`,
	}
	for _, event := range data {
		if err := converter.HandleData(event); err != nil {
			t.Fatal(err)
		}
	}
	converter.Close()

	starts := eventPayloads(recorder.Body.Bytes(), "content_block_start")
	if len(starts) != 2 {
		t.Fatalf("expected two tool blocks, got %d: %s", len(starts), recorder.Body.String())
	}
	for index, payload := range starts {
		if got := intField(payload, "index"); got != index {
			t.Fatalf("block %d has index %d", index, got)
		}
	}
	deltas := eventPayloads(recorder.Body.Bytes(), "content_block_delta")
	if len(deltas) != 2 {
		t.Fatalf("expected one aggregated argument delta per tool block, got %d", len(deltas))
	}
	expected := []int{0, 1}
	for i, payload := range deltas {
		if got := intField(payload, "index"); got != expected[i] {
			t.Fatalf("delta %d has index %d, want %d", i, got, expected[i])
		}
	}
	stops := eventPayloads(recorder.Body.Bytes(), "content_block_stop")
	if len(stops) != 2 {
		t.Fatalf("expected two block stops, got %d", len(stops))
	}
}

func eventPayloads(raw []byte, wantedEvent string) []map[string]any {
	lines := strings.Split(string(raw), "\n")
	var result []map[string]any
	for i := 0; i+1 < len(lines); i++ {
		if strings.TrimSpace(lines[i]) != "event: "+wantedEvent {
			continue
		}
		const prefix = "data: "
		if !strings.HasPrefix(lines[i+1], prefix) {
			continue
		}
		var payload map[string]any
		if json.Unmarshal([]byte(strings.TrimPrefix(lines[i+1], prefix)), &payload) == nil {
			result = append(result, payload)
		}
	}
	return result
}

func intField(payload map[string]any, key string) int {
	value, _ := payload[key].(float64)
	return int(value)
}

func TestConfigCanBeEncodedAsYAMLWithoutSecrets(t *testing.T) {
	config := DefaultConfig()
	config.Upstream.APIKey = "test-only"
	encoded, err := yaml.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(encoded, []byte("enabled: false")) {
		t.Fatalf("unexpected config encoding: %s", encoded)
	}
}

func TestTranslateRequestStripsThinkingBlocksWhenConfigured(t *testing.T) {
	config := testConfig("http://127.0.0.1:1")
	config.Thinking.Unsupported = "strip"
	request := MessageRequest{
		Model:     "claude-test",
		MaxTokens: 16,
		Messages: []Message{{
			Role:    "assistant",
			Content: json.RawMessage(`[{"type":"thinking","thinking":"private reasoning"},{"type":"text","text":"answer"}]`),
		}},
	}

	translated, err := TranslateRequest(request, config.Routes[0], config)
	if err != nil {
		t.Fatal(err)
	}
	if len(translated.Messages) != 1 || string(translated.Messages[0].Content) != `[{"type":"text","text":"answer"}]` {
		t.Fatalf("thinking block was not stripped: %+v", translated.Messages)
	}
}

func TestServerStreamsClaudeEventsInOrder(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Error("mock upstream does not support flushing")
			return
		}
		events := []string{
			`{"id":"stream-1","model":"claude-test","choices":[{"delta":{"role":"assistant"}}]}`,
			`{"choices":[{"delta":{"content":"hello"}}]}`,
			`{"choices":[{"delta":{},"finish_reason":"stop"}]}`,
		}
		for _, event := range events {
			_, _ = io.WriteString(w, "data: "+event+"\n\n")
			flusher.Flush()
		}
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()
	request := basicMessageRequest()
	request.Stream = true
	response, err := http.DefaultClient.Do(httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, request)))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK {
		t.Fatalf("stream returned %d: %s", response.StatusCode, payload)
	}
	if !strings.HasPrefix(response.Header.Get("Content-Type"), "text/event-stream") {
		t.Fatalf("unexpected stream content type: %q", response.Header.Get("Content-Type"))
	}
	names := eventNames(payload)
	expected := []string{"message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"}
	if strings.Join(names, ",") != strings.Join(expected, ",") {
		t.Fatalf("unexpected event sequence: %v; body=%s", names, payload)
	}
	if !strings.Contains(string(payload), `"type":"text_delta"`) || !strings.Contains(string(payload), `"text":"hello"`) {
		t.Fatalf("text delta was not translated: %s", payload)
	}
}

func TestServerRejectsOversizedUpstreamSuccessResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, strings.Repeat("x", 8192))
	}))
	defer upstream.Close()

	config := testConfig(upstream.URL)
	config.MaxBodyBytes = 4096
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		t.Fatal(err)
	}
	adapter := httptest.NewServer(server.Handler())
	defer adapter.Close()

	response, err := http.DefaultClient.Do(httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, basicMessageRequest())))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("expected 502 for oversized upstream response, got %d: %s", response.StatusCode, payload)
	}
	var errorPayload ClaudeErrorResponse
	if err := json.Unmarshal(payload, &errorPayload); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorPayload.Error.Message, "exceeds") {
		t.Fatalf("expected body limit error, got %+v", errorPayload)
	}
}

func TestServerEmitsStreamErrorWhenUpstreamBodyExceedsLimit(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"id\":\"stream-1\",\"model\":\"claude-test\",\"choices\":[{\"delta\":{\"content\":\"hello\"}}]}\n\n")
		_, _ = io.WriteString(w, strings.Repeat("x", 2048))
	}))
	defer upstream.Close()

	config := testConfig(upstream.URL)
	config.MaxBodyBytes = 512
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		t.Fatal(err)
	}
	adapter := httptest.NewServer(server.Handler())
	defer adapter.Close()

	request := basicMessageRequest()
	request.Stream = true
	response, err := http.DefaultClient.Do(httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, request)))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK {
		t.Fatalf("stream returned %d: %s", response.StatusCode, payload)
	}
	names := eventNames(payload)
	if len(names) == 0 || names[len(names)-1] != "error" {
		t.Fatalf("expected terminal stream error, got %v: %s", names, payload)
	}
	if strings.Contains(string(payload), "event: message_stop") || strings.Contains(string(payload), "event: message_delta") {
		t.Fatalf("oversized stream emitted normal completion events: %s", payload)
	}
	if !strings.Contains(string(payload), "body exceeds 512 bytes") {
		t.Fatalf("expected body limit error, got: %s", payload)
	}
}

func eventNames(raw []byte) []string {
	lines := strings.Split(string(raw), "\n")
	var names []string
	for _, line := range lines {
		if strings.HasPrefix(line, "event: ") {
			names = append(names, strings.TrimPrefix(line, "event: "))
		}
	}
	return names
}

func TestServerMapsUpstreamTimeoutToClaudeTimeoutError(t *testing.T) {
	upstreamStarted := make(chan struct{})
	upstreamCanceled := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(upstreamStarted)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		if flusher, ok := w.(http.Flusher); ok {
			flusher.Flush()
		}
		<-r.Context().Done()
		close(upstreamCanceled)
	}))
	defer upstream.Close()

	config := testConfig(upstream.URL)
	config.Upstream.RequestTimeoutSeconds = 1
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		t.Fatal(err)
	}
	adapter := httptest.NewServer(server.Handler())
	defer adapter.Close()

	response, err := http.DefaultClient.Do(httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, basicMessageRequest())))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	payload, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusGatewayTimeout {
		t.Fatalf("expected 504, got %d: %s", response.StatusCode, payload)
	}
	var errorPayload ClaudeErrorResponse
	if err := json.Unmarshal(payload, &errorPayload); err != nil {
		t.Fatal(err)
	}
	if errorPayload.Error.Type != "timeout_error" {
		t.Fatalf("expected timeout_error, got %+v", errorPayload)
	}
	select {
	case <-upstreamStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream request did not start")
	}
	select {
	case <-upstreamCanceled:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream request was not canceled after timeout")
	}
}

func TestServerCancelsUpstreamWhenClientDisconnects(t *testing.T) {
	upstreamStarted := make(chan struct{})
	upstreamCanceled := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(upstreamStarted)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		if flusher, ok := w.(http.Flusher); ok {
			flusher.Flush()
		}
		<-r.Context().Done()
		close(upstreamCanceled)
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()

	ctx, cancel := context.WithCancel(context.Background())
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, adapter.URL+"/v1/messages", bytes.NewReader(messageRequestJSON(t, basicMessageRequest())))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("x-api-key", "client-key")
	result := make(chan error, 1)
	go func() {
		response, requestErr := http.DefaultClient.Do(request)
		if response != nil {
			_ = response.Body.Close()
		}
		result <- requestErr
	}()

	select {
	case <-upstreamStarted:
	case <-time.After(2 * time.Second):
		cancel()
		t.Fatal("upstream request did not start")
	}
	cancel()

	select {
	case <-upstreamCanceled:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream request was not canceled")
	}
	select {
	case requestErr := <-result:
		if requestErr == nil || !errors.Is(requestErr, context.Canceled) {
			t.Fatalf("expected client cancellation, got %v", requestErr)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("client request did not finish after cancellation")
	}
}

func TestServerMapsUpstreamConnectionFailureToBadGateway(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	upstreamURL := upstream.URL
	upstream.Close()

	adapter := newTestServer(t, upstreamURL)
	defer adapter.Close()

	response, err := http.DefaultClient.Do(httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, basicMessageRequest())))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	payload, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("expected 502 for upstream connection failure, got %d: %s", response.StatusCode, payload)
	}
	var errorPayload ClaudeErrorResponse
	if err := json.Unmarshal(payload, &errorPayload); err != nil {
		t.Fatal(err)
	}
	if errorPayload.Error.Type != "api_error" {
		t.Fatalf("expected api_error, got %+v", errorPayload)
	}
}

func TestSSEConverterRedactsUpstreamSecrets(t *testing.T) {
	recorder := httptest.NewRecorder()
	converter := NewSSEConverter(recorder, recorder, "request-1", "claude-test", "internal-upstream-key")
	converter.EmitError(upstreamAPIError(http.StatusBadGateway, "provider rejected internal-upstream-key", "request-1"))

	payload := recorder.Body.String()
	if strings.Contains(payload, "internal-upstream-key") {
		t.Fatalf("stream error leaked upstream secret: %s", payload)
	}
	if !strings.Contains(payload, "[redacted]") {
		t.Fatalf("stream error was not redacted: %s", payload)
	}
	if names := eventNames(recorder.Body.Bytes()); len(names) != 1 || names[0] != "error" {
		t.Fatalf("unexpected stream error events: %v", names)
	}
}

// ===== Tests targeting the "duplicate upstream calls" root causes =====

// TestDuplicateXRequestIDDedupesUpstreamCall simulates the exact failure mode:
// Claude Code retries the same x-request-id after a partial stream / timeout.
// The adapter MUST collapse concurrent retries into exactly ONE upstream call.
func TestDuplicateXRequestIDDedupesUpstreamCall(t *testing.T) {
	var upstreamCalls atomic.Int32
	// Make upstream slow enough that both requests arrive while it's in-flight.
	upstreamStarted := make(chan struct{}, 1)
	releaseUpstream := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamCalls.Add(1)
		select {
		case upstreamStarted <- struct{}{}:
		default:
		}
		<-releaseUpstream
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chat-1","model":"claude-test","choices":[{"index":0,"message":{"role":"assistant","content":"deduped"},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}`)
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()

	body := messageRequestJSON(t, basicMessageRequest())
	const sharedRID = "dedup-key-0001"

	makeReq := func() *http.Request {
		req, err := http.NewRequest(http.MethodPost, adapter.URL+"/v1/messages", bytes.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("x-api-key", "client-key")
		req.Header.Set("x-request-id", sharedRID)
		return req
	}

	results := make(chan error, 2)
	sendOne := func() {
		resp, err := http.DefaultClient.Do(makeReq())
		if err == nil {
			_, _ = io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
		}
		results <- err
	}

	// Launch request A; wait until upstream has definitely begun.
	go sendOne()
	select {
	case <-upstreamStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("first request did not reach upstream in time")
	}
	// Now launch request B with the SAME x-request-id while A is still in-flight.
	go sendOne()
	// Give B enough time to register as a waiter.
	time.Sleep(100 * time.Millisecond)
	// Release the upstream response; both goroutines will then finish.
	close(releaseUpstream)
	for i := 0; i < 2; i++ {
		select {
		case err := <-results:
			if err != nil {
				t.Fatalf("request %d failed: %v", i+1, err)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("request %d never completed", i+1)
		}
	}

	if n := upstreamCalls.Load(); n != 1 {
		t.Fatalf("duplicate x-request-id produced %d upstream calls, want exactly 1 (dedup broken)", n)
	}
}

// TestStreamRequestUsesTextEventStreamAcceptHeader verifies root-cause fix:
// stream=true requests must send Accept: text/event-stream upstream, otherwise
// many providers return a non-SSE payload and Claude Code retries indefinitely.
func TestStreamRequestUsesTextEventStreamAcceptHeader(t *testing.T) {
	var gotAccept atomic.Value
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAccept.Store(r.Header.Get("Accept"))
		w.Header().Set("Content-Type", "text/event-stream")
		flusher, _ := w.(http.Flusher)
		events := []string{
			`{"id":"s-1","model":"claude-test","choices":[{"delta":{"content":"ok"}}]}`,
		}
		for _, e := range events {
			_, _ = io.WriteString(w, "data: "+e+"\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		}
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
		if flusher != nil {
			flusher.Flush()
		}
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()
	req := basicMessageRequest()
	req.Stream = true
	httpReq := httpRequestWithKey(t, adapter.URL+"/v1/messages", messageRequestJSON(t, req))
	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	resp.Body.Close()

	accept, _ := gotAccept.Load().(string)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected status %d", resp.StatusCode)
	}
	if !strings.Contains(accept, "text/event-stream") {
		t.Fatalf("stream request sent Accept=%q upstream, want text/event-stream (root-cause-1 unfixed)", accept)
	}
}

// TestRecentCacheReplaysNonStreamResult verifies the 30s TTL replay cache:
// a second request with the same id after the first has fully completed
// does NOT hit upstream again.
func TestRecentCacheReplaysNonStreamResult(t *testing.T) {
	var upstreamCalls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chat-recent","model":"claude-test","choices":[{"index":0,"message":{"role":"assistant","content":"cached"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}`)
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()

	body := messageRequestJSON(t, basicMessageRequest())
	const rid = "recent-cache-1"
	send := func() string {
		req, err := http.NewRequest(http.MethodPost, adapter.URL+"/v1/messages", bytes.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("x-api-key", "client-key")
		req.Header.Set("x-request-id", rid)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		payload, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("status=%d payload=%s", resp.StatusCode, payload)
		}
		return string(payload)
	}

	first := send()
	second := send()
	if upstreamCalls.Load() != 1 {
		t.Fatalf("same x-request-id sent twice produced %d upstream calls, want 1 (recent-cache dedup broken)", upstreamCalls.Load())
	}
	if first != second {
		t.Fatalf("replayed cached result differs: first=%q second=%q", first, second)
	}
	if !strings.Contains(second, `"text":"cached"`) {
		t.Fatalf("replay payload missing translated content: %s", second)
	}
}

// TestCountTokensRealisticClaudeCodeProbes ensures that Claude Code's exact real-world
// token counting requests (e.g. without max_tokens, with tools schema, with "foo", with CJK)
// succeed locally without reaching upstream and return reasonable token estimates.
func TestCountTokensRealisticClaudeCodeProbes(t *testing.T) {
	var upstreamCalls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamCalls.Add(1)
		t.Error("upstream should NEVER be called for count_tokens")
	}))
	defer upstream.Close()

	adapter := newTestServer(t, upstream.URL)
	defer adapter.Close()

	cases := []struct {
		name    string
		body    string
		minWant int
	}{
		{
			name: "real Claude Code tool counting with foo and without max_tokens",
			body: `{"model":"claude-test","messages":[{"role":"user","content":"foo"}],"tools":[{"name":"test_tool","description":"does something useful","input_schema":{"type":"object","properties":{"arg":{"type":"string"}}}}]}`,
			minWant: 15,
		},
		{
			name: "real Claude Code prompt fragment without max_tokens",
			body: `{"model":"claude-test","messages":[{"role":"user","content":"When referencing files in your responses, format them as markdown links so the user can click to open them."}]}`,
			minWant: 20,
		},
		{
			name: "real Claude Code Chinese prompt fragment",
			body: `{"model":"claude-test","messages":[{"role":"user","content":"你好世界，这是一个测试文本，用于验证中文分词 Token 估算是否合理准确。"}]}`,
			minWant: 25,
		},
		{
			name: "tools only without messages",
			body: `{"model":"claude-test","tools":[{"name":"SendMessage","description":"Send a message to another agent","input_schema":{"type":"object","properties":{"to":{"type":"string"},"message":{"type":"string"}},"required":["to","message"]}}]}`,
			minWant: 30,
		},
		{
			name: "system prompt only",
			body: `{"model":"claude-test","system":"You are a helpful programming assistant that follows strict coding guidelines."}`,
			minWant: 15,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req, err := http.NewRequest(http.MethodPost, adapter.URL+"/v1/messages/count_tokens", strings.NewReader(tc.body))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Authorization", "Bearer client-key")
			req.Header.Set("Content-Type", "application/json")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()

			payload, _ := io.ReadAll(resp.Body)
			if resp.StatusCode != http.StatusOK {
				t.Fatalf("expected 200 OK, got %d: %s", resp.StatusCode, payload)
			}

			var result struct {
				InputTokens int `json:"input_tokens"`
			}
			if err := json.Unmarshal(payload, &result); err != nil {
				t.Fatalf("decode json: %v", err)
			}
			if result.InputTokens < tc.minWant {
				t.Fatalf("got %d input_tokens, want at least %d", result.InputTokens, tc.minWant)
			}
		})
	}

	if upstreamCalls.Load() != 0 {
		t.Fatalf("count_tokens hit upstream %d times, want 0", upstreamCalls.Load())
	}
}

