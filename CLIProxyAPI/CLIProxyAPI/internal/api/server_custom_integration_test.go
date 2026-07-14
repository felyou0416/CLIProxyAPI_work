package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/tidwall/gjson"
)

func TestServerBillingAndUsage(t *testing.T) {
	server := newTestServer(t)
	tests := []struct {
		path       string
		wantObject string
	}{
		{path: "/v1/dashboard/billing/subscription", wantObject: "billing_subscription"},
		{path: "/v1/dashboard/billing/usage", wantObject: "list"},
		{path: "/v1/usage", wantObject: "list"},
	}

	for _, tc := range tests {
		t.Run(tc.path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			req.Header.Set("Authorization", "Bearer test-key")
			rr := httptest.NewRecorder()
			server.engine.ServeHTTP(rr, req)
			if rr.Code != http.StatusOK {
				t.Fatalf("status = %d, want %d", rr.Code, http.StatusOK)
			}
			var resp map[string]any
			if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
				t.Fatalf("parse response: %v", err)
			}
			if resp["object"] != tc.wantObject {
				t.Fatalf("object = %v, want %s", resp["object"], tc.wantObject)
			}
		})
	}
}

func TestServerChatToMediaProxyForAgnesMappedModels(t *testing.T) {
	server := newTestServer(t)
	var seen []string
	mediaProxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Fatalf("media proxy path = %s", r.URL.Path)
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode forwarded request: %v", err)
		}
		model, _ := req["model"].(string)
		seen = append(seen, model)
		content := "![image](https://apihub.agnes-ai.com/images/mapped.png)"
		if strings.Contains(strings.ToLower(model), "video") {
			content = "[video](https://platform-outputs.agnes-ai.space/videos/mapped.mp4)"
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-media","object":"chat.completion","model":"` + model + `","choices":[{"message":{"role":"assistant","content":"` + content + `"},"finish_reason":"stop"}]}`))
	}))
	defer mediaProxy.Close()
	t.Setenv("CLIPROXYAPI_MEDIA_PROXY_URL", mediaProxy.URL)

	tests := []struct {
		model       string
		wantContent string
	}{
		{model: "agnes-agnes-image-2.1-flash", wantContent: "![image](https://apihub.agnes-ai.com/images/mapped.png)"},
		{model: "agnes-agnes-video-v2.0", wantContent: "[video](https://platform-outputs.agnes-ai.space/videos/mapped.mp4)"},
	}
	for _, tc := range tests {
		t.Run(tc.model, func(t *testing.T) {
			body := strings.NewReader(`{"model":"` + tc.model + `","messages":[{"role":"user","content":"quick test"}],"stream":false}`)
			req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", body)
			req.Header.Set("Authorization", "Bearer test-key")
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()
			server.engine.ServeHTTP(rr, req)
			if rr.Code != http.StatusOK {
				t.Fatalf("status = %d, body=%s", rr.Code, rr.Body.String())
			}
			if content := gjson.GetBytes(rr.Body.Bytes(), "choices.0.message.content").String(); content != tc.wantContent {
				t.Fatalf("content = %q, want %q", content, tc.wantContent)
			}
		})
	}
	if len(seen) != len(tests) {
		t.Fatalf("media proxy requests = %d, want %d", len(seen), len(tests))
	}
}

func TestServerClaudeMessagesToMediaProxyForAgnesMappedModels(t *testing.T) {
	server := newTestServer(t)
	var forwardedModel string
	mediaProxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("decode forwarded request: %v", err)
		}
		forwardedModel, _ = req["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-media","object":"chat.completion","model":"agnes-agnes-image-2.1-flash","choices":[{"message":{"role":"assistant","content":"![image](https://apihub.agnes-ai.com/images/messages.png)"},"finish_reason":"stop"}]}`))
	}))
	defer mediaProxy.Close()
	t.Setenv("CLIPROXYAPI_MEDIA_PROXY_URL", mediaProxy.URL)

	body := strings.NewReader(`{"model":"agnes-agnes-image-2.1-flash","messages":[{"role":"user","content":"quick claude media test"}],"max_tokens":64}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/messages?beta=true", body)
	req.Header.Set("Authorization", "Bearer test-key")
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	server.engine.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rr.Code, rr.Body.String())
	}
	if forwardedModel != "agnes-agnes-image-2.1-flash" {
		t.Fatalf("forwarded model = %q", forwardedModel)
	}
}
