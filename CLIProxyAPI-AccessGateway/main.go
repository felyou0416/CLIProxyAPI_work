package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

const maxRequestBody = 64 << 20

type modelAlias struct {
	Name  string `yaml:"name"`
	Alias string `yaml:"alias"`
}

type modelSource struct {
	Models []modelAlias `yaml:"models"`
}

type gatewayConfig struct {
	OAuthModelAlias     map[string][]modelAlias `yaml:"oauth-model-alias"`
	OpenAICompatibility []modelSource           `yaml:"openai-compatibility"`
	ClaudeAPIKey        []modelSource           `yaml:"claude-api-key"`
	CodexAPIKey         []modelSource           `yaml:"codex-api-key"`
	GeminiAPIKey        []modelSource           `yaml:"gemini-api-key"`
	VertexAPIKey        []modelSource           `yaml:"vertex-api-key"`
	XAIAPIKey           []modelSource           `yaml:"xai-api-key"`
}

type gateway struct {
	allowed map[string]struct{}
	proxy   *httputil.ReverseProxy
}

func main() {
	listen := flag.String("listen", "127.0.0.1:8317", "client-facing listen address")
	upstream := flag.String("upstream", "http://127.0.0.1:8318", "internal CPA URL")
	configPath := flag.String("config", "", "generated CPA YAML config")
	flag.Parse()

	if strings.TrimSpace(*configPath) == "" {
		log.Fatal("-config is required")
	}
	allowed, err := loadAllowedModels(*configPath)
	if err != nil {
		log.Fatalf("load model allowlist: %v", err)
	}
	target, err := url.Parse(*upstream)
	if err != nil {
		log.Fatalf("parse upstream URL: %v", err)
	}

	handler := newGateway(target, allowed)
	server := &http.Server{
		Addr:              *listen,
		Handler:           handler,
		ReadHeaderTimeout: 15 * time.Second,
	}
	log.Printf("access gateway listening on %s, upstream=%s, public_models=%d", *listen, target, len(allowed))
	if errServe := server.ListenAndServe(); errServe != nil && errServe != http.ErrServerClosed {
		log.Fatal(errServe)
	}
}

func loadAllowedModels(path string) (map[string]struct{}, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg gatewayConfig
	if errUnmarshal := yaml.Unmarshal(raw, &cfg); errUnmarshal != nil {
		return nil, errUnmarshal
	}
	allowed := make(map[string]struct{})
	add := func(alias string) {
		value := normalizeModel(alias)
		if value != "" {
			allowed[value] = struct{}{}
		}
	}
	for _, aliases := range cfg.OAuthModelAlias {
		for _, entry := range aliases {
			if !strings.EqualFold(strings.TrimSpace(entry.Name), strings.TrimSpace(entry.Alias)) {
				add(entry.Alias)
			}
		}
	}
	for _, sources := range [][]modelSource{
		cfg.OpenAICompatibility,
		cfg.ClaudeAPIKey,
		cfg.CodexAPIKey,
		cfg.GeminiAPIKey,
		cfg.VertexAPIKey,
		cfg.XAIAPIKey,
	} {
		for _, source := range sources {
			for _, entry := range source.Models {
				add(entry.Alias)
			}
		}
	}
	if len(allowed) == 0 {
		return nil, fmt.Errorf("no mapped or aggregate model aliases were found")
	}
	return allowed, nil
}

func newGateway(target *url.URL, allowed map[string]struct{}) *gateway {
	reverseProxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := reverseProxy.Director
	reverseProxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host
	}
	reverseProxy.ModifyResponse = func(resp *http.Response) error {
		if !isModelsPath(resp.Request.URL.Path) || resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil
		}
		return filterModelList(resp, allowed)
	}
	return &gateway{allowed: allowed, proxy: reverseProxy}
}

func (g *gateway) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	if isWebSocketUpgrade(req) {
		writeModelError(w, http.StatusUpgradeRequired, "websocket access is disabled on the public model gateway")
		return
	}
	if model := modelFromPath(req.URL.Path); model != "" && !g.isAllowed(model) {
		writeModelError(w, http.StatusNotFound, "model is not publicly available")
		return
	}
	if requestMayContainModel(req) {
		model, err := readRequestModel(req)
		if err != nil {
			writeModelError(w, http.StatusBadRequest, err.Error())
			return
		}
		if model != "" && !g.isAllowed(model) {
			writeModelError(w, http.StatusNotFound, "model is not publicly available")
			return
		}
	}
	g.proxy.ServeHTTP(w, req)
}

func (g *gateway) isAllowed(model string) bool {
	_, ok := g.allowed[normalizeModel(model)]
	return ok
}

func normalizeModel(model string) string {
	value := strings.TrimSpace(model)
	value = strings.TrimPrefix(value, "models/")
	return strings.ToLower(value)
}

func isModelsPath(path string) bool {
	clean := strings.TrimSuffix(path, "/")
	return clean == "/models" || clean == "/v1/models" || clean == "/v1beta/models"
}

func modelFromPath(path string) string {
	for _, prefix := range []string{"/v1beta/models/", "/v1/models/", "/models/"} {
		if strings.HasPrefix(path, prefix) {
			value := strings.TrimPrefix(path, prefix)
			if index := strings.IndexAny(value, ":/"); index >= 0 {
				value = value[:index]
			}
			return value
		}
	}
	return ""
}

func requestMayContainModel(req *http.Request) bool {
	if req.Method != http.MethodPost && req.Method != http.MethodPut && req.Method != http.MethodPatch {
		return false
	}
	contentType := strings.ToLower(req.Header.Get("Content-Type"))
	return contentType == "" || strings.Contains(contentType, "json")
}

func readRequestModel(req *http.Request) (string, error) {
	if req.Body == nil {
		return "", nil
	}
	raw, err := io.ReadAll(io.LimitReader(req.Body, maxRequestBody+1))
	if err != nil {
		return "", fmt.Errorf("read request body: %w", err)
	}
	if len(raw) > maxRequestBody {
		return "", fmt.Errorf("request body exceeds %d bytes", maxRequestBody)
	}
	req.Body = io.NopCloser(bytes.NewReader(raw))
	req.ContentLength = int64(len(raw))
	if len(bytes.TrimSpace(raw)) == 0 {
		return "", nil
	}
	var payload struct {
		Model string `json:"model"`
	}
	if errUnmarshal := json.Unmarshal(raw, &payload); errUnmarshal != nil {
		return "", fmt.Errorf("invalid JSON request body")
	}
	return payload.Model, nil
}

func filterModelList(resp *http.Response, allowed map[string]struct{}) error {
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	var payload map[string]any
	if errUnmarshal := json.Unmarshal(raw, &payload); errUnmarshal != nil {
		return errUnmarshal
	}
	for _, key := range []string{"data", "models"} {
		items, ok := payload[key].([]any)
		if !ok {
			continue
		}
		filtered := make([]any, 0, len(items))
		for _, item := range items {
			entry, okEntry := item.(map[string]any)
			if !okEntry {
				continue
			}
			modelID, _ := entry["id"].(string)
			if modelID == "" {
				modelID, _ = entry["name"].(string)
			}
			if _, okAllowed := allowed[normalizeModel(modelID)]; okAllowed {
				filtered = append(filtered, item)
			}
		}
		payload[key] = filtered
	}
	filteredRaw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	resp.Body = io.NopCloser(bytes.NewReader(filteredRaw))
	resp.ContentLength = int64(len(filteredRaw))
	resp.Header.Set("Content-Length", fmt.Sprintf("%d", len(filteredRaw)))
	return nil
}

func isWebSocketUpgrade(req *http.Request) bool {
	return strings.EqualFold(strings.TrimSpace(req.Header.Get("Upgrade")), "websocket")
}

func writeModelError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"error": map[string]any{
			"message": message,
			"type":    "model_not_found",
			"code":    "model_not_found",
		},
	})
}
