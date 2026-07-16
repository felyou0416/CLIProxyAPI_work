package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Config struct {
	Listen        string               `json:"listen"`
	AuthDir       string               `json:"auth_dir"`
	Providers     []Provider           `json:"providers"`
	AuthProviders []AuthProviderConfig `json:"auth_providers"`
	loadedAuth    map[string]struct{}
}

type Provider struct {
	Name    string            `json:"name"`
	BaseURL string            `json:"base_url"`
	APIKey  string            `json:"api_key"`
	Headers map[string]string `json:"headers"`
	Models  []ModelConfig     `json:"models"`
}

type AuthProviderConfig struct {
	Provider   string            `json:"provider"`
	Headers    map[string]string `json:"headers"`
	ModelRules []AuthModelRule   `json:"model_rules"`
}

type AuthModelRule struct {
	MatchContains     string `json:"match_contains"`
	MatchPrefix       string `json:"match_prefix"`
	MatchSuffix       string `json:"match_suffix"`
	Type              string `json:"type"`
	Endpoint          string `json:"endpoint"`
	RetrieveEndpoint  string `json:"retrieve_endpoint"`
	Method            string `json:"method"`
	RequestFormat     string `json:"request_format"`
	ResponseFormat    string `json:"response_format"`
	DefaultSize       string `json:"default_size"`
	DefaultWidth      int    `json:"default_width"`
	DefaultHeight     int    `json:"default_height"`
	DefaultNumFrames  int    `json:"default_num_frames"`
	DefaultFrameRate  int    `json:"default_frame_rate"`
	PollIntervalMS    int    `json:"poll_interval_ms"`
	PollTimeoutSecond int    `json:"poll_timeout_seconds"`
}

type ModelConfig struct {
	Name               string `json:"name"`
	Alias              string `json:"alias"`
	Type               string `json:"type"`
	Endpoint           string `json:"endpoint"`
	RetrieveEndpoint   string `json:"retrieve_endpoint"`
	Method             string `json:"method"`
	RequestFormat      string `json:"request_format"`
	ResponseFormat     string `json:"response_format"`
	DefaultSize        string `json:"default_size"`
	DefaultWidth       int    `json:"default_width"`
	DefaultHeight      int    `json:"default_height"`
	DefaultNumFrames   int    `json:"default_num_frames"`
	DefaultFrameRate   int    `json:"default_frame_rate"`
	PollIntervalMillis int    `json:"poll_interval_ms"`
	PollTimeoutSeconds int    `json:"poll_timeout_seconds"`
}

type modelRoute struct {
	Provider Provider
	Model    ModelConfig
	Key      string
}

type Server struct {
	models   map[string][]modelRoute
	next     map[string]uint64
	mu       sync.Mutex
	bindings *videoBindingStore
	client   *http.Client
}

type videoBinding struct {
	ModelAlias string
	RouteKey   string
	UpstreamID string
	ExpiresAt  time.Time
}

type videoBindingStore struct {
	mu      sync.RWMutex
	entries map[string]videoBinding
}

func newVideoBindingStore() *videoBindingStore {
	return &videoBindingStore{entries: make(map[string]videoBinding)}
}

func (s *videoBindingStore) set(id, modelAlias string, ttl time.Duration) {
	s.setWithUpstreamID(id, modelAlias, "", id, ttl)
}

func (s *videoBindingStore) setWithUpstreamID(id, modelAlias string, routeKey string, upstreamID string, ttl time.Duration) {
	id = strings.TrimSpace(id)
	modelAlias = strings.TrimSpace(modelAlias)
	routeKey = strings.TrimSpace(routeKey)
	upstreamID = strings.TrimSpace(upstreamID)
	if id == "" || modelAlias == "" {
		return
	}
	if upstreamID == "" {
		upstreamID = id
	}
	if ttl <= 0 {
		ttl = 3 * time.Hour
	}
	s.mu.Lock()
	s.entries[id] = videoBinding{ModelAlias: modelAlias, RouteKey: routeKey, UpstreamID: upstreamID, ExpiresAt: time.Now().Add(ttl)}
	s.mu.Unlock()
}

func (s *videoBindingStore) get(id string) (videoBinding, bool) {
	s.mu.RLock()
	b, ok := s.entries[strings.TrimSpace(id)]
	s.mu.RUnlock()
	if !ok || time.Now().After(b.ExpiresAt) {
		if ok {
			s.mu.Lock()
			delete(s.entries, strings.TrimSpace(id))
			s.mu.Unlock()
		}
		return videoBinding{}, false
	}
	return b, true
}

func main() {
	configPath := flag.String("config", "config.json", "path to media proxy config")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	server, err := NewServer(cfg)
	if err != nil {
		log.Fatalf("init server: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/chat/completions", server.handleChatCompletions)
	mux.HandleFunc("/v1/images/generations", server.handleImagesGenerations)
	mux.HandleFunc("/v1/videos", server.handleVideosCreate)
	mux.HandleFunc("/v1/videos/generations", server.handleVideosCreate)
	mux.HandleFunc("/v1/videos/", server.handleVideosRetrieve)

	addr := strings.TrimSpace(cfg.Listen)
	if addr == "" {
		addr = "127.0.0.1:8320"
	}
	log.Printf("media proxy listening on http://%s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}

func loadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return Config{}, err
	}
	return loadAuthProviders(cfg)
}

func loadAuthProviders(cfg Config) (Config, error) {
	authDir := strings.TrimSpace(cfg.AuthDir)
	if authDir == "" {
		return cfg, nil
	}
	if cfg.loadedAuth == nil {
		cfg.loadedAuth = make(map[string]struct{})
	}
	entries, err := os.ReadDir(authDir)
	if err != nil {
		return cfg, fmt.Errorf("read auth_dir: %w", err)
	}
	for _, entry := range entries {
		if entry.IsDir() {
			if err := loadAuthProviderDir(&cfg, filepath.Join(authDir, entry.Name())); err != nil {
				return cfg, err
			}
			continue
		}
		if strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			if err := loadAuthFile(&cfg, filepath.Join(authDir, entry.Name())); err != nil {
				return cfg, err
			}
		}
	}
	return cfg, nil
}

func loadAuthProviderDir(cfg *Config, dir string) error {
	return filepath.WalkDir(dir, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			return nil
		}
		return loadAuthFile(cfg, path)
	})
}

func loadAuthFile(cfg *Config, path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil
	}
	if disabled, _ := raw["disabled"].(bool); disabled {
		return nil
	}
	content, _ := raw["content"].(map[string]any)
	if content == nil {
		content = raw
	}
	providerName := strings.ToLower(strings.TrimSpace(fmt.Sprint(content["provider"])))
	baseURL := strings.TrimSpace(fmt.Sprint(content["base_url"]))
	apiKey := strings.TrimSpace(fmt.Sprint(content["api_key"]))
	if providerName == "" || baseURL == "" || apiKey == "" {
		return nil
	}
	provider := Provider{
		Name:    providerName,
		BaseURL: strings.TrimRight(baseURL, "/"),
		APIKey:  apiKey,
		Headers: headersForAuthProvider(providerName, cfg.AuthProviders),
		Models:  mediaModelsFromAuthContent(providerName, baseURL, content, cfg.AuthProviders),
	}
	if len(provider.Models) == 0 {
		return nil
	}
	dedupeKey := authDedupeKey(provider)
	if _, ok := cfg.loadedAuth[dedupeKey]; ok {
		return nil
	}
	cfg.loadedAuth[dedupeKey] = struct{}{}
	cfg.Providers = append(cfg.Providers, provider)
	return nil
}

func authDedupeKey(provider Provider) string {
	modelNames := make([]string, 0, len(provider.Models))
	for _, model := range provider.Models {
		modelNames = append(modelNames, strings.ToLower(strings.TrimSpace(model.Name)))
	}
	sort.Strings(modelNames)
	return strings.Join([]string{
		strings.ToLower(strings.TrimSpace(provider.Name)),
		strings.TrimRight(strings.TrimSpace(provider.BaseURL), "/"),
		strings.TrimSpace(provider.APIKey),
		strings.Join(modelNames, ","),
	}, "\x00")
}

func headersForAuthProvider(provider string, rules []AuthProviderConfig) map[string]string {
	headers := map[string]string{"Content-Type": "application/json"}
	for _, rule := range rules {
		if !sameProvider(provider, rule.Provider) {
			continue
		}
		for key, value := range rule.Headers {
			if strings.TrimSpace(key) != "" && strings.TrimSpace(value) != "" {
				headers[key] = value
			}
		}
	}
	return headers
}

func mediaModelsFromAuthContent(provider string, baseURL string, content map[string]any, rules []AuthProviderConfig) []ModelConfig {
	names := authModelNames(content)
	models := make([]ModelConfig, 0, len(names))
	for _, name := range names {
		for _, providerRule := range rules {
			if !sameProvider(provider, providerRule.Provider) {
				continue
			}
			for _, modelRule := range providerRule.ModelRules {
				if !modelRuleMatches(name, modelRule) {
					continue
				}
				models = append(models, modelFromRule(name, baseURL, modelRule))
				goto nextModel
			}
		}
	nextModel:
	}
	return models
}

func sameProvider(left string, right string) bool {
	return strings.EqualFold(strings.TrimSpace(left), strings.TrimSpace(right))
}

func modelRuleMatches(model string, rule AuthModelRule) bool {
	lower := strings.ToLower(strings.TrimSpace(model))
	if contains := strings.ToLower(strings.TrimSpace(rule.MatchContains)); contains != "" && !strings.Contains(lower, contains) {
		return false
	}
	if prefix := strings.ToLower(strings.TrimSpace(rule.MatchPrefix)); prefix != "" && !strings.HasPrefix(lower, prefix) {
		return false
	}
	if suffix := strings.ToLower(strings.TrimSpace(rule.MatchSuffix)); suffix != "" && !strings.HasSuffix(lower, suffix) {
		return false
	}
	return rule.MatchContains != "" || rule.MatchPrefix != "" || rule.MatchSuffix != ""
}

func modelFromRule(name string, baseURL string, rule AuthModelRule) ModelConfig {
	return ModelConfig{
		Name:               name,
		Alias:              name,
		Type:               rule.Type,
		Endpoint:           expandEndpointTemplate(rule.Endpoint, baseURL),
		RetrieveEndpoint:   expandEndpointTemplate(rule.RetrieveEndpoint, baseURL),
		Method:             rule.Method,
		RequestFormat:      rule.RequestFormat,
		ResponseFormat:     rule.ResponseFormat,
		DefaultSize:        rule.DefaultSize,
		DefaultWidth:       rule.DefaultWidth,
		DefaultHeight:      rule.DefaultHeight,
		DefaultNumFrames:   rule.DefaultNumFrames,
		DefaultFrameRate:   rule.DefaultFrameRate,
		PollIntervalMillis: rule.PollIntervalMS,
		PollTimeoutSeconds: rule.PollTimeoutSecond,
	}
}

func expandEndpointTemplate(value string, baseURL string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	value = strings.ReplaceAll(value, "{origin}", strings.TrimRight(originURL(baseURL), "/"))
	value = strings.ReplaceAll(value, "{base_url}", strings.TrimRight(baseURL, "/"))
	return value
}

func authModelNames(content map[string]any) []string {
	seen := map[string]struct{}{}
	var out []string
	add := func(value any) {
		model := strings.TrimSpace(fmt.Sprint(value))
		if model == "" || model == "<nil>" {
			return
		}
		key := strings.ToLower(model)
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		out = append(out, model)
	}
	add(content["model"])
	if items, ok := content["models"].([]any); ok {
		for _, item := range items {
			add(item)
		}
	}
	return out
}

func originURL(rawURL string) string {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return strings.TrimRight(strings.TrimSpace(rawURL), "/")
	}
	return parsed.Scheme + "://" + parsed.Host
}

func NewServer(cfg Config) (*Server, error) {
	models := make(map[string][]modelRoute)
	for _, provider := range cfg.Providers {
		provider.Name = strings.TrimSpace(provider.Name)
		provider.BaseURL = strings.TrimRight(strings.TrimSpace(provider.BaseURL), "/")
		if provider.Name == "" {
			return nil, errors.New("provider name is required")
		}
		if provider.BaseURL == "" {
			return nil, fmt.Errorf("provider %q base_url is required", provider.Name)
		}
		for _, model := range provider.Models {
			model.Name = strings.TrimSpace(model.Name)
			model.Alias = strings.TrimSpace(model.Alias)
			model.Type = strings.ToLower(strings.TrimSpace(model.Type))
			if model.Alias == "" {
				model.Alias = model.Name
			}
			if model.Name == "" || model.Alias == "" {
				return nil, fmt.Errorf("provider %q has a model without name/alias", provider.Name)
			}
			if model.Type != "image" && model.Type != "video" {
				return nil, fmt.Errorf("model %q type must be image or video", model.Alias)
			}
			if strings.TrimSpace(model.Endpoint) == "" {
				return nil, fmt.Errorf("model %q endpoint is required", model.Alias)
			}
			route := modelRoute{Provider: provider, Model: model, Key: routeKey(provider, model)}
			addModelRoute(models, model.Alias, route)
			addModelRoute(models, model.Name, route)
			if providerPrefixAlias := provider.Name + "-" + model.Name; !strings.EqualFold(providerPrefixAlias, model.Name) {
				addModelRoute(models, providerPrefixAlias, route)
			}
		}
	}
	return &Server{
		models:   models,
		next:     make(map[string]uint64),
		bindings: newVideoBindingStore(),
		client:   &http.Client{Timeout: 5 * time.Minute},
	}, nil
}

func addModelRoute(models map[string][]modelRoute, alias string, route modelRoute) {
	key := strings.ToLower(strings.TrimSpace(alias))
	if key == "" {
		return
	}
	for _, existing := range models[key] {
		if existing.Key == route.Key {
			return
		}
	}
	models[key] = append(models[key], route)
}

func routeKey(provider Provider, model ModelConfig) string {
	return strings.Join([]string{
		strings.ToLower(strings.TrimSpace(provider.Name)),
		strings.TrimRight(strings.TrimSpace(provider.BaseURL), "/"),
		strings.TrimSpace(provider.APIKey),
		strings.ToLower(strings.TrimSpace(model.Name)),
		strings.ToLower(strings.TrimSpace(model.Alias)),
	}, "\x00")
}

func (s *Server) handleChatCompletions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONError(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST is required")
		return
	}
	raw, err := readBody(r)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", err.Error())
		return
	}
	var req map[string]any
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", "body must be valid JSON")
		return
	}

	modelName := stringField(req, "model")
	route, ok := s.findModel(modelName)
	if !ok {
		writeJSONError(w, http.StatusBadRequest, "model_not_found", "unknown media model: "+modelName)
		return
	}

	prompt := promptFromChat(req)
	if prompt == "" {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", "chat request must include a user prompt")
		return
	}

	payload, err := buildMediaPayload(route.Model, req, prompt)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", err.Error())
		return
	}
	upstream, err := s.callUpstream(r.Context(), route, route.Model.Endpoint, payload, methodOrDefault(route.Model.Method))
	if err != nil {
		writeJSONError(w, http.StatusBadGateway, "upstream_error", err.Error())
		return
	}

	content := ""
	switch route.Model.Type {
	case "image":
		urls := extractImageURLs(upstream)
		if len(urls) == 0 {
			writeRawChat(w, modelName, upstream)
			return
		}
		content = markdownImages(urls)
	case "video":
		videoURL, videoID := extractVideoResult(upstream)
		if videoURL == "" && videoID != "" && route.Model.RetrieveEndpoint != "" {
			s.bindings.setWithUpstreamID(videoID, route.Model.Alias, route.Key, videoID, 3*time.Hour)
			videoURL, err = s.pollVideo(r.Context(), route, videoID)
			if err != nil {
				// Keep chat clients from hanging forever: return a usable task handle.
				writeChat(w, modelName, videoPendingChatContent(videoID, err))
				return
			}
		}
		if videoURL == "" {
			if videoID != "" {
				writeChat(w, modelName, videoPendingChatContent(videoID, nil))
				return
			}
			writeRawChat(w, modelName, upstream)
			return
		}
		content = "[video](" + videoURL + ")"
	}

	writeChat(w, modelName, content)
}

func (s *Server) handleImagesGenerations(w http.ResponseWriter, r *http.Request) {
	s.handleDirectCreate(w, r, "image")
}

func (s *Server) handleVideosCreate(w http.ResponseWriter, r *http.Request) {
	s.handleDirectCreate(w, r, "video")
}

func (s *Server) handleDirectCreate(w http.ResponseWriter, r *http.Request, mediaType string) {
	if r.Method != http.MethodPost {
		writeJSONError(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST is required")
		return
	}
	raw, err := readBody(r)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", err.Error())
		return
	}
	var req map[string]any
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", "body must be valid JSON")
		return
	}
	modelName := stringField(req, "model")
	route, ok := s.findModel(modelName)
	if !ok || route.Model.Type != mediaType {
		writeJSONError(w, http.StatusBadRequest, "model_not_found", "unknown "+mediaType+" model: "+modelName)
		return
	}
	payload, err := buildDirectPayload(route.Model, req)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", err.Error())
		return
	}
	resp, err := s.callUpstream(r.Context(), route, route.Model.Endpoint, payload, methodOrDefault(route.Model.Method))
	if err != nil {
		writeJSONError(w, http.StatusBadGateway, "upstream_error", err.Error())
		return
	}
	if route.Model.Type == "video" {
		s.bindVideoResponseIDs(resp, route, 3*time.Hour)
	}
	writeJSONBytes(w, http.StatusOK, resp)
}

func (s *Server) handleVideosRetrieve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONError(w, http.StatusMethodNotAllowed, "method_not_allowed", "GET is required")
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/videos/")
	id = strings.TrimSpace(id)
	if id == "" {
		writeJSONError(w, http.StatusBadRequest, "invalid_request_error", "video id is required")
		return
	}
	modelName := strings.TrimSpace(r.URL.Query().Get("model"))
	upstreamID := id
	routeKey := ""
	if modelName == "" {
		if binding, ok := s.bindings.get(id); ok {
			modelName = binding.ModelAlias
			routeKey = binding.RouteKey
			if strings.TrimSpace(binding.UpstreamID) != "" {
				upstreamID = binding.UpstreamID
			}
		}
	}
	route, ok := s.findModelWithRouteKey(modelName, routeKey)
	if !ok || route.Model.Type != "video" || route.Model.RetrieveEndpoint == "" {
		writeJSONError(w, http.StatusBadRequest, "model_not_found", "video model is required for retrieve")
		return
	}
	resp, err := s.retrieveVideo(r.Context(), route, upstreamID)
	if err != nil {
		writeJSONError(w, http.StatusBadGateway, "upstream_error", err.Error())
		return
	}
	writeJSONBytes(w, http.StatusOK, resp)
}

func (s *Server) findModel(model string) (modelRoute, bool) {
	key := strings.ToLower(strings.TrimSpace(model))
	routes := s.models[key]
	if len(routes) == 0 {
		return modelRoute{}, false
	}
	s.mu.Lock()
	index := s.next[key] % uint64(len(routes))
	s.next[key]++
	s.mu.Unlock()
	return routes[index], true
}

func (s *Server) findModelWithRouteKey(model string, wantedRouteKey string) (modelRoute, bool) {
	key := strings.ToLower(strings.TrimSpace(model))
	routes := s.models[key]
	if len(routes) == 0 {
		return modelRoute{}, false
	}
	wantedRouteKey = strings.TrimSpace(wantedRouteKey)
	if wantedRouteKey != "" {
		for _, route := range routes {
			if route.Key == wantedRouteKey {
				return route, true
			}
		}
	}
	return s.findModel(model)
}

func buildMediaPayload(model ModelConfig, chat map[string]any, prompt string) ([]byte, error) {
	req := cloneMap(chat)
	delete(req, "messages")
	delete(req, "stream")
	req["model"] = model.Name
	req["prompt"] = prompt
	if images := imagesFromChat(chat); len(images) > 0 {
		if _, ok := req["image"]; !ok {
			if _, ok := req["images"]; !ok {
				if len(images) == 1 {
					req["image"] = images[0]
				} else {
					req["images"] = images
				}
			}
		}
	}
	return buildDirectPayload(model, req)
}

func buildDirectPayload(model ModelConfig, req map[string]any) ([]byte, error) {
	format := strings.ToLower(strings.TrimSpace(model.RequestFormat))
	if format == "" {
		format = "passthrough"
	}
	switch format {
	case "passthrough":
		req = cloneMap(req)
		req["model"] = model.Name
		return json.Marshal(req)
	case "openai-image":
		out := cloneMap(req)
		out["model"] = model.Name
		if _, ok := out["prompt"]; !ok || strings.TrimSpace(fmt.Sprint(out["prompt"])) == "" {
			return nil, errors.New("prompt is required")
		}
		applyDefaultSize(out, model.DefaultSize)
		if _, ok := out["response_format"]; !ok {
			out["response_format"] = "url"
		}
		normalizeOpenAIImageInputs(out)
		if isImageEditEndpoint(model.Endpoint) {
			if !hasOpenAIImageInput(out) {
				return nil, errors.New("image or images is required for image edits")
			}
		}
		return json.Marshal(out)
	case "agnes-image":
		out := cloneMap(req)
		out["model"] = model.Name
		delete(out, "tags")
		if _, ok := out["prompt"]; !ok || strings.TrimSpace(fmt.Sprint(out["prompt"])) == "" {
			return nil, errors.New("prompt is required")
		}
		applyDefaultSize(out, model.DefaultSize)
		if _, ok := out["size"]; !ok || strings.TrimSpace(fmt.Sprint(out["size"])) == "" {
			return nil, errors.New("size is required")
		}
		extra := ensureObject(out, "extra_body")
		if image, ok := out["image"]; ok {
			extra["image"] = image
			delete(out, "image")
		}
		if format, ok := out["response_format"]; ok {
			extra["response_format"] = format
			delete(out, "response_format")
		}
		if _, ok := extra["response_format"]; !ok && strings.TrimSpace(model.ResponseFormat) != "" && model.ResponseFormat != "auto" {
			extra["response_format"] = model.ResponseFormat
		}
		return json.Marshal(out)
	case "openai-video":
		out := cloneMap(req)
		out["model"] = model.Name
		if _, ok := out["prompt"]; !ok || strings.TrimSpace(fmt.Sprint(out["prompt"])) == "" {
			return nil, errors.New("prompt is required")
		}
		return json.Marshal(out)
	case "agnes-video":
		out := cloneMap(req)
		out["model"] = model.Name
		delete(out, "tags")
		if _, ok := out["prompt"]; !ok || strings.TrimSpace(fmt.Sprint(out["prompt"])) == "" {
			return nil, errors.New("prompt is required")
		}
		applyVideoDefaults(out, model)
		extra := ensureObject(out, "extra_body")
		if image, ok := out["image"]; ok {
			if images := anySlice(image); len(images) > 1 {
				extra["image"] = images
				delete(out, "image")
			}
		}
		if images, ok := out["images"]; ok {
			if values := anySlice(images); len(values) == 1 {
				out["image"] = values[0]
			} else {
				extra["image"] = images
			}
			delete(out, "images")
		}
		return json.Marshal(out)
	default:
		return nil, fmt.Errorf("unsupported request_format %q", model.RequestFormat)
	}
}

func (s *Server) callUpstream(ctx context.Context, route modelRoute, endpoint string, body []byte, method string) ([]byte, error) {
	method = methodOrDefault(method)
	url := upstreamURL(route.Provider.BaseURL, endpoint)
	var reader io.Reader
	if method != http.MethodGet {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, reader)
	if err != nil {
		return nil, err
	}
	if method != http.MethodGet {
		req.Header.Set("Content-Type", "application/json")
	}
	if strings.TrimSpace(route.Provider.APIKey) != "" {
		req.Header.Set("Authorization", "Bearer "+route.Provider.APIKey)
	}
	for key, value := range route.Provider.Headers {
		if strings.TrimSpace(key) != "" && strings.TrimSpace(value) != "" {
			req.Header.Set(key, value)
		}
	}
	resp, err := s.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("upstream %s returned %d: %s", url, resp.StatusCode, strings.TrimSpace(string(data)))
	}
	return data, nil
}

func (s *Server) retrieveVideo(ctx context.Context, route modelRoute, id string) ([]byte, error) {
	endpoint := strings.ReplaceAll(route.Model.RetrieveEndpoint, "{id}", id)
	endpoint = strings.ReplaceAll(endpoint, "{request_id}", id)
	endpoint = strings.ReplaceAll(endpoint, "{video_id}", id)
	endpoint = strings.ReplaceAll(endpoint, "{model}", route.Model.Name)
	return s.callUpstream(ctx, route, endpoint, nil, http.MethodGet)
}

func (s *Server) bindVideoResponseIDs(raw []byte, route modelRoute, ttl time.Duration) {
	root := parseJSON(raw)
	upstreamID := firstString(root, "video_id", "request_id", "task_id", "id")
	if upstreamID == "" {
		upstreamID = jsonPathString(root, "data.id")
	}
	for _, id := range uniqueStrings([]string{
		stringField(root, "video_id"),
		stringField(root, "request_id"),
		stringField(root, "task_id"),
		stringField(root, "id"),
		jsonPathString(root, "data.id"),
	}) {
		s.bindings.setWithUpstreamID(id, route.Model.Alias, route.Key, upstreamID, ttl)
	}
}

func (s *Server) pollVideo(ctx context.Context, route modelRoute, id string) (string, error) {
	interval := time.Duration(route.Model.PollIntervalMillis) * time.Millisecond
	if interval <= 0 {
		interval = 3 * time.Second
	}
	timeout := time.Duration(route.Model.PollTimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 3 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	var lastErr error
	var lastStatus string
	check := func() (string, bool, error) {
		resp, err := s.retrieveVideo(ctx, route, id)
		if err != nil {
			lastErr = err
			return "", false, nil
		}
		videoURL, _ := extractVideoResult(resp)
		if videoURL != "" {
			return videoURL, true, nil
		}
		status := strings.ToLower(firstString(parseJSON(resp), "status", "state", "internal_status"))
		if status != "" {
			lastStatus = status
		}
		if status == "failed" || status == "error" || status == "cancelled" || status == "canceled" {
			return "", true, fmt.Errorf("video generation failed with status %q", status)
		}
		return "", false, nil
	}
	if videoURL, done, err := check(); done {
		return videoURL, err
	}
	for {
		select {
		case <-ctx.Done():
			if lastErr != nil {
				return "", fmt.Errorf("video polling timed out after %s; last error: %v", timeout, lastErr)
			}
			if lastStatus != "" {
				return "", fmt.Errorf("video polling timed out after %s; last status: %s", timeout, lastStatus)
			}
			return "", fmt.Errorf("video polling timed out after %s", timeout)
		case <-ticker.C:
			if videoURL, done, err := check(); done {
				return videoURL, err
			}
		}
	}
}

func promptFromChat(req map[string]any) string {
	messages, _ := req["messages"].([]any)
	for i := len(messages) - 1; i >= 0; i-- {
		msg, _ := messages[i].(map[string]any)
		if strings.ToLower(stringField(msg, "role")) != "user" {
			continue
		}
		return contentText(msg["content"])
	}
	return ""
}

func imagesFromChat(req map[string]any) []map[string]any {
	if images := normalizeImageRefs(req["images"]); len(images) > 0 {
		return images
	}
	if images := normalizeImageRefs(req["image"]); len(images) > 0 {
		return images
	}
	messages, _ := req["messages"].([]any)
	var out []map[string]any
	for _, item := range messages {
		msg, _ := item.(map[string]any)
		out = append(out, contentImages(msg["content"])...)
	}
	return uniqueImageRefs(out)
}

func contentText(content any) string {
	switch v := content.(type) {
	case string:
		return strings.TrimSpace(v)
	case []any:
		var parts []string
		for _, item := range v {
			obj, _ := item.(map[string]any)
			if strings.ToLower(stringField(obj, "type")) == "text" {
				if text := stringField(obj, "text"); text != "" {
					parts = append(parts, text)
				}
			}
		}
		return strings.TrimSpace(strings.Join(parts, "\n"))
	default:
		return ""
	}
}

func contentImages(content any) []map[string]any {
	switch v := content.(type) {
	case []any:
		var out []map[string]any
		for _, item := range v {
			obj, _ := item.(map[string]any)
			if obj == nil {
				continue
			}
			typeName := strings.ToLower(stringField(obj, "type"))
			switch typeName {
			case "image_url", "input_image", "image":
				if ref := imageRefFromAny(obj); len(ref) > 0 {
					out = append(out, ref)
				}
			}
			if nested := obj["image_url"]; nested != nil {
				if ref := imageRefFromAny(nested); len(ref) > 0 {
					out = append(out, ref)
				}
			}
		}
		return out
	default:
		return nil
	}
}

func imageRefFromAny(value any) map[string]any {
	switch v := value.(type) {
	case string:
		url := strings.TrimSpace(v)
		if url == "" {
			return nil
		}
		return map[string]any{"url": url}
	case map[string]any:
		if url := stringField(v, "url"); url != "" {
			return map[string]any{"url": url}
		}
		if imageURL := v["image_url"]; imageURL != nil {
			return imageRefFromAny(imageURL)
		}
		if fileID := stringField(v, "file_id"); fileID != "" {
			return map[string]any{"file_id": fileID}
		}
	}
	return nil
}

func normalizeImageRefs(value any) []map[string]any {
	if value == nil {
		return nil
	}
	switch v := value.(type) {
	case []any:
		var out []map[string]any
		for _, item := range v {
			if ref := imageRefFromAny(item); len(ref) > 0 {
				out = append(out, ref)
			}
		}
		return uniqueImageRefs(out)
	case []string:
		var out []map[string]any
		for _, item := range v {
			if ref := imageRefFromAny(item); len(ref) > 0 {
				out = append(out, ref)
			}
		}
		return uniqueImageRefs(out)
	default:
		if ref := imageRefFromAny(value); len(ref) > 0 {
			return []map[string]any{ref}
		}
		return nil
	}
}

func uniqueImageRefs(values []map[string]any) []map[string]any {
	if len(values) == 0 {
		return nil
	}
	seen := make(map[string]struct{}, len(values))
	out := make([]map[string]any, 0, len(values))
	for _, value := range values {
		key := stringField(value, "url")
		if key == "" {
			key = "file:" + stringField(value, "file_id")
		}
		if key == "" || key == "file:" {
			continue
		}
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, value)
	}
	return out
}

func normalizeOpenAIImageInputs(req map[string]any) {
	if images := normalizeImageRefs(req["images"]); len(images) > 0 {
		if len(images) == 1 {
			req["image"] = images[0]
			delete(req, "images")
		} else {
			req["images"] = images
			delete(req, "image")
		}
		return
	}
	if images := normalizeImageRefs(req["image"]); len(images) > 0 {
		if len(images) == 1 {
			req["image"] = images[0]
		} else {
			req["images"] = images
			delete(req, "image")
		}
	}
}

func hasOpenAIImageInput(req map[string]any) bool {
	return len(normalizeImageRefs(req["image"])) > 0 || len(normalizeImageRefs(req["images"])) > 0
}

func isImageEditEndpoint(endpoint string) bool {
	lower := strings.ToLower(strings.TrimSpace(endpoint))
	return strings.Contains(lower, "/images/edits") || strings.Contains(lower, "image-edit") || strings.HasSuffix(lower, "/edits")
}

func videoPendingChatContent(videoID string, err error) string {
	videoID = strings.TrimSpace(videoID)
	if videoID == "" {
		if err != nil {
			return "video generation is still pending: " + err.Error()
		}
		return "video generation is still pending"
	}
	msg := "video task created: " + videoID + "\nstatus: pending\npoll: GET /v1/videos/" + videoID
	if err != nil {
		msg += "\nnote: " + err.Error()
	}
	return msg
}

func applyDefaultSize(req map[string]any, defaultSize string) {
	if strings.TrimSpace(defaultSize) == "" {
		return
	}
	if _, ok := req["size"]; ok && strings.TrimSpace(fmt.Sprint(req["size"])) != "" {
		return
	}
	req["size"] = strings.TrimSpace(defaultSize)
}

func applyVideoDefaults(req map[string]any, model ModelConfig) {
	applySizeAsWidthHeight(req)
	if model.DefaultWidth > 0 {
		setDefaultInt(req, "width", model.DefaultWidth)
	}
	if model.DefaultHeight > 0 {
		setDefaultInt(req, "height", model.DefaultHeight)
	}
	if model.DefaultNumFrames > 0 {
		setDefaultInt(req, "num_frames", model.DefaultNumFrames)
	}
	if model.DefaultFrameRate > 0 {
		setDefaultInt(req, "frame_rate", model.DefaultFrameRate)
	}
}

func applySizeAsWidthHeight(req map[string]any) {
	raw := strings.TrimSpace(fmt.Sprint(req["size"]))
	if raw == "" || raw == "<nil>" {
		return
	}
	parts := strings.Split(strings.ToLower(raw), "x")
	if len(parts) != 2 {
		return
	}
	width, errW := strconv.Atoi(strings.TrimSpace(parts[0]))
	height, errH := strconv.Atoi(strings.TrimSpace(parts[1]))
	if errW != nil || errH != nil || width <= 0 || height <= 0 {
		return
	}
	if _, ok := req["width"]; !ok {
		req["width"] = width
	}
	if _, ok := req["height"]; !ok {
		req["height"] = height
	}
	delete(req, "size")
}

func setDefaultInt(req map[string]any, key string, value int) {
	if _, ok := req[key]; ok && strings.TrimSpace(fmt.Sprint(req[key])) != "" {
		return
	}
	req[key] = value
}

func anySlice(value any) []any {
	switch v := value.(type) {
	case []any:
		return v
	case []string:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, item)
		}
		return out
	default:
		return nil
	}
}

func ensureObject(req map[string]any, key string) map[string]any {
	if existing, ok := req[key].(map[string]any); ok {
		return existing
	}
	obj := make(map[string]any)
	req[key] = obj
	return obj
}

func extractImageURLs(raw []byte) []string {
	root := parseJSON(raw)
	var urls []string
	for _, path := range []string{"url", "image.url", "image_url"} {
		if value := jsonPathString(root, path); value != "" {
			urls = append(urls, value)
		}
	}
	urls = append(urls, stringArrayPath(root, "images", "url")...)
	urls = append(urls, stringArrayPath(root, "data", "url")...)
	return uniqueStrings(urls)
}

func extractVideoResult(raw []byte) (videoURL string, videoID string) {
	root := parseJSON(raw)
	for _, path := range []string{"video.url", "video_url", "url", "data.url", "output.video.url", "remixed_from_video_id"} {
		if value := jsonPathString(root, path); value != "" {
			videoURL = value
			break
		}
	}
	for _, path := range []string{"video_id", "request_id", "task_id", "id", "data.id"} {
		if value := jsonPathString(root, path); value != "" {
			videoID = value
			break
		}
	}
	return videoURL, videoID
}

func parseJSON(raw []byte) map[string]any {
	var root map[string]any
	_ = json.Unmarshal(raw, &root)
	return root
}

func jsonPathString(root map[string]any, path string) string {
	var current any = root
	for _, part := range strings.Split(path, ".") {
		obj, ok := current.(map[string]any)
		if !ok {
			return ""
		}
		var exists bool
		current, exists = obj[part]
		if !exists || current == nil {
			return ""
		}
	}
	switch v := current.(type) {
	case string:
		return strings.TrimSpace(v)
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(v)
	default:
		return strings.TrimSpace(fmt.Sprint(v))
	}
}

func stringArrayPath(root map[string]any, arrayKey, field string) []string {
	items, _ := root[arrayKey].([]any)
	var out []string
	for _, item := range items {
		obj, _ := item.(map[string]any)
		if value := stringField(obj, field); value != "" {
			out = append(out, value)
		}
	}
	return out
}

func firstString(root map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := stringField(root, key); value != "" {
			return value
		}
	}
	return ""
}

func markdownImages(urls []string) string {
	var b strings.Builder
	for i, url := range urls {
		if i > 0 {
			b.WriteString("\n")
		}
		b.WriteString("![image](")
		b.WriteString(url)
		b.WriteString(")")
	}
	return b.String()
}

func writeChat(w http.ResponseWriter, model, content string) {
	resp := map[string]any{
		"id":      "chatcmpl-media-proxy",
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   model,
		"choices": []map[string]any{{
			"index": 0,
			"message": map[string]any{
				"role":    "assistant",
				"content": content,
			},
			"finish_reason": "stop",
		}},
	}
	writeJSON(w, http.StatusOK, resp)
}

func writeRawChat(w http.ResponseWriter, model string, raw []byte) {
	writeChat(w, model, strings.TrimSpace(string(raw)))
}

func writeJSONError(w http.ResponseWriter, status int, code string, message string) {
	writeJSON(w, status, map[string]any{
		"error": map[string]any{
			"code":    code,
			"message": message,
			"type":    code,
		},
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	data, err := json.Marshal(value)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeJSONBytes(w, status, data)
}

func writeJSONBytes(w http.ResponseWriter, status int, data []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(data)
}

func readBody(r *http.Request) ([]byte, error) {
	defer r.Body.Close()
	data, err := io.ReadAll(io.LimitReader(r.Body, 32<<20))
	if err != nil {
		return nil, err
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return nil, errors.New("body is required")
	}
	return data, nil
}

func cloneMap(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func stringField(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	value, ok := m[key]
	if !ok || value == nil {
		return ""
	}
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v)
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(v)
	default:
		return strings.TrimSpace(fmt.Sprint(v))
	}
}

func normalizeEndpoint(endpoint string) string {
	endpoint = strings.TrimSpace(endpoint)
	if endpoint == "" {
		return "/"
	}
	if !strings.HasPrefix(endpoint, "/") {
		return "/" + endpoint
	}
	return endpoint
}

func upstreamURL(baseURL string, endpoint string) string {
	endpoint = strings.TrimSpace(endpoint)
	if strings.HasPrefix(strings.ToLower(endpoint), "http://") || strings.HasPrefix(strings.ToLower(endpoint), "https://") {
		return endpoint
	}
	return strings.TrimRight(baseURL, "/") + normalizeEndpoint(endpoint)
}

func methodOrDefault(method string) string {
	method = strings.ToUpper(strings.TrimSpace(method))
	if method == "" {
		return http.MethodPost
	}
	return method
}

func uniqueStrings(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}
