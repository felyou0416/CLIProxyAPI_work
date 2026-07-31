package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
)

func TestLoadAllowedModelsUsesAliasesOnly(t *testing.T) {
	file, err := os.CreateTemp(t.TempDir(), "config-*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	config := `oauth-model-alias:
  codex:
    - name: "gpt-raw"
      alias: "codex-public"
      fork: false
    - name: "gpt-raw"
      alias: "smart"
      fork: false
    - name: "identity"
      alias: "identity"
openai-compatibility:
  - name: agnes
    models:
      - name: upstream-image
        alias: agnes-image
`
	if _, errWrite := file.WriteString(config); errWrite != nil {
		t.Fatal(errWrite)
	}
	_ = file.Close()
	allowed, err := loadAllowedModels(file.Name())
	if err != nil {
		t.Fatal(err)
	}
	for _, model := range []string{"codex-public", "smart", "agnes-image"} {
		if _, ok := allowed[model]; !ok {
			t.Fatalf("expected %q to be allowed", model)
		}
	}
	for _, model := range []string{"gpt-raw", "upstream-image", "identity"} {
		if _, ok := allowed[model]; ok {
			t.Fatalf("did not expect raw model %q", model)
		}
	}
}

func TestGatewayFiltersListAndRejectsRawCalls(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		switch req.URL.Path {
		case "/v1/models":
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{
				map[string]any{"id": "raw-model"},
				map[string]any{"id": "mapped-model"},
				map[string]any{"id": "aggregate-model"},
			}})
		case "/v1/chat/completions":
			body, _ := io.ReadAll(req.Body)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(body)
		default:
			http.NotFound(w, req)
		}
	}))
	defer upstream.Close()
	target, _ := url.Parse(upstream.URL)
	server := httptest.NewServer(newGateway(target, map[string]struct{}{
		"mapped-model": {}, "aggregate-model": {},
	}))
	defer server.Close()

	resp, err := http.Get(server.URL + "/v1/models")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	text := string(raw)
	if strings.Contains(text, "raw-model") || !strings.Contains(text, "mapped-model") || !strings.Contains(text, "aggregate-model") {
		t.Fatalf("unexpected filtered model list: %s", text)
	}

	rawResp, err := http.Post(server.URL+"/v1/chat/completions", "application/json", strings.NewReader(`{"model":"raw-model"}`))
	if err != nil {
		t.Fatal(err)
	}
	_ = rawResp.Body.Close()
	if rawResp.StatusCode != http.StatusNotFound {
		t.Fatalf("raw model status = %d, want 404", rawResp.StatusCode)
	}

	mappedResp, err := http.Post(server.URL+"/v1/chat/completions", "application/json", strings.NewReader(`{"model":"mapped-model"}`))
	if err != nil {
		t.Fatal(err)
	}
	mappedBody, _ := io.ReadAll(mappedResp.Body)
	_ = mappedResp.Body.Close()
	if mappedResp.StatusCode != http.StatusOK || !strings.Contains(string(mappedBody), "mapped-model") {
		t.Fatalf("mapped response status=%d body=%s", mappedResp.StatusCode, mappedBody)
	}
}

func TestGatewayRejectsRawGeminiPathAndWebSockets(t *testing.T) {
	target, _ := url.Parse("http://127.0.0.1:1")
	handler := newGateway(target, map[string]struct{}{"mapped-model": {}})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/v1beta/models/raw-model:generateContent", nil))
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("Gemini raw model status = %d, want 404", recorder.Code)
	}

	recorder = httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/v1/responses", nil)
	request.Header.Set("Upgrade", "websocket")
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUpgradeRequired {
		t.Fatalf("websocket status = %d, want 426", recorder.Code)
	}
}

func TestGatewayReloadsAllowedModelsWithoutRestart(t *testing.T) {
	configPath := t.TempDir() + "/config.yaml"
	if err := os.WriteFile(configPath, []byte("oauth-model-alias:\n  codex:\n    - name: raw-a\n      alias: public-a\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	target, _ := url.Parse("http://127.0.0.1:1")
	handler := newGateway(target, map[string]struct{}{"public-a": {}})

	if err := os.WriteFile(configPath, []byte("oauth-model-alias:\n  codex:\n    - name: raw-b\n      alias: public-b\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := handler.reloadAllowedModels(configPath); err != nil {
		t.Fatal(err)
	}
	if handler.isAllowed("public-a") || !handler.isAllowed("public-b") {
		t.Fatal("gateway did not atomically replace the model allowlist")
	}
}
