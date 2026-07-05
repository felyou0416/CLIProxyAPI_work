package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestExtractImageURLsIgnoresMissingPaths(t *testing.T) {
	urls := extractImageURLs([]byte(`{"data":[{"url":"https://example.com/image.png"}]}`))
	if len(urls) != 1 || urls[0] != "https://example.com/image.png" {
		t.Fatalf("urls = %#v", urls)
	}
}

func TestExtractVideoResultIgnoresMissingPaths(t *testing.T) {
	videoURL, videoID := extractVideoResult([]byte(`{"request_id":"video_123","status":"queued"}`))
	if videoURL != "" {
		t.Fatalf("videoURL = %q, want empty", videoURL)
	}
	if videoID != "video_123" {
		t.Fatalf("videoID = %q, want video_123", videoID)
	}
}

func TestStringFieldMissingReturnsEmpty(t *testing.T) {
	if got := stringField(map[string]any{}, "missing"); got != "" {
		t.Fatalf("missing field = %q, want empty", got)
	}
}

func TestChatCompletionsUsesConfiguredMethod(t *testing.T) {
	var gotMethod string
	var gotBody map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":[{"url":"https://example.com/out.png"}]}`))
	}))
	defer upstream.Close()

	srv, err := NewServer(Config{Providers: []Provider{{
		Name:    "test",
		BaseURL: upstream.URL,
		Models: []ModelConfig{{
			Name:          "img-upstream",
			Alias:         "img",
			Type:          "image",
			Endpoint:      "/generate",
			Method:        http.MethodPut,
			RequestFormat: "openai-image",
		}},
	}}})
	if err != nil {
		t.Fatal(err)
	}

	body := bytes.NewBufferString(`{"model":"img","messages":[{"role":"user","content":"draw"}]}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", body)
	rr := httptest.NewRecorder()
	srv.handleChatCompletions(rr, req.WithContext(context.Background()))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rr.Code, rr.Body.String())
	}
	if gotMethod != http.MethodPut {
		t.Fatalf("method = %q, want PUT", gotMethod)
	}
	if gotBody["model"] != "img-upstream" {
		t.Fatalf("upstream model = %#v, want img-upstream", gotBody["model"])
	}
}

func TestBuildDirectPayloadAgnesImageShape(t *testing.T) {
	payload, err := buildDirectPayload(ModelConfig{
		Name:           "agnes-image-2.1-flash",
		Type:           "image",
		RequestFormat:  "agnes-image",
		ResponseFormat: "url",
		DefaultSize:    "1024x768",
	}, map[string]any{
		"model":           "alias",
		"prompt":          "draw",
		"response_format": "b64_json",
		"image":           []any{"https://example.com/input.png"},
		"tags":            []any{"img2img"},
	})
	if err != nil {
		t.Fatal(err)
	}

	var got map[string]any
	if err := json.Unmarshal(payload, &got); err != nil {
		t.Fatal(err)
	}
	if got["model"] != "agnes-image-2.1-flash" {
		t.Fatalf("model = %#v", got["model"])
	}
	if got["size"] != "1024x768" {
		t.Fatalf("size = %#v", got["size"])
	}
	if _, ok := got["response_format"]; ok {
		t.Fatal("response_format should not be top-level")
	}
	if _, ok := got["image"]; ok {
		t.Fatal("image should not be top-level")
	}
	if _, ok := got["tags"]; ok {
		t.Fatal("tags should be removed")
	}
	extra, ok := got["extra_body"].(map[string]any)
	if !ok {
		t.Fatalf("extra_body = %#v", got["extra_body"])
	}
	if extra["response_format"] != "b64_json" {
		t.Fatalf("extra_body.response_format = %#v", extra["response_format"])
	}
	images, ok := extra["image"].([]any)
	if !ok || len(images) != 1 || images[0] != "https://example.com/input.png" {
		t.Fatalf("extra_body.image = %#v", extra["image"])
	}
}

func TestBuildDirectPayloadAgnesImageRequiresSize(t *testing.T) {
	_, err := buildDirectPayload(ModelConfig{
		Name:          "agnes-image-2.1-flash",
		Type:          "image",
		RequestFormat: "agnes-image",
	}, map[string]any{
		"prompt": "draw",
	})
	if err == nil || err.Error() != "size is required" {
		t.Fatalf("err = %v, want size is required", err)
	}
}

func TestBuildDirectPayloadAgnesVideoShape(t *testing.T) {
	payload, err := buildDirectPayload(ModelConfig{
		Name:          "agnes-video-v2.0",
		Type:          "video",
		RequestFormat: "agnes-video",
	}, map[string]any{
		"model":      "alias",
		"prompt":     "animate",
		"images":     []any{"https://example.com/one.png", "https://example.com/two.png"},
		"tags":       []any{"img2video"},
		"num_frames": float64(121),
		"frame_rate": float64(24),
	})
	if err != nil {
		t.Fatal(err)
	}

	var got map[string]any
	if err := json.Unmarshal(payload, &got); err != nil {
		t.Fatal(err)
	}
	if got["model"] != "agnes-video-v2.0" {
		t.Fatalf("model = %#v", got["model"])
	}
	if _, ok := got["images"]; ok {
		t.Fatal("images should not be top-level")
	}
	if _, ok := got["tags"]; ok {
		t.Fatal("tags should be removed")
	}
	extra, ok := got["extra_body"].(map[string]any)
	if !ok {
		t.Fatalf("extra_body = %#v", got["extra_body"])
	}
	images, ok := extra["image"].([]any)
	if !ok || len(images) != 2 {
		t.Fatalf("extra_body.image = %#v", extra["image"])
	}
}

func TestExtractVideoResultAgnesCompletedResponse(t *testing.T) {
	videoURL, videoID := extractVideoResult([]byte(`{
		"id":"task_123",
		"video_id":"video_456",
		"status":"completed",
		"remixed_from_video_id":"https://storage.googleapis.com/agnes-aigc/out.mp4"
	}`))
	if videoURL != "https://storage.googleapis.com/agnes-aigc/out.mp4" {
		t.Fatalf("videoURL = %q", videoURL)
	}
	if videoID != "video_456" {
		t.Fatalf("videoID = %q", videoID)
	}
}

func TestRetrieveVideoReplacesAgnesPlaceholders(t *testing.T) {
	var gotPath string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.String()
		_, _ = w.Write([]byte(`{"status":"completed","remixed_from_video_id":"https://example.com/out.mp4"}`))
	}))
	defer upstream.Close()

	srv, err := NewServer(Config{Providers: []Provider{{
		Name:    "agnes",
		BaseURL: upstream.URL,
		Models: []ModelConfig{{
			Name:             "agnes-video-v2.0",
			Alias:            "agnes-video-v2.0",
			Type:             "video",
			Endpoint:         "/v1/videos",
			RetrieveEndpoint: "/agnesapi?video_id={video_id}&model_name={model}",
			RequestFormat:    "agnes-video",
		}},
	}}})
	if err != nil {
		t.Fatal(err)
	}

	route, ok := srv.findModel("agnes-video-v2.0")
	if !ok {
		t.Fatal("model route not found")
	}
	if _, err := srv.retrieveVideo(context.Background(), route, "video_456"); err != nil {
		t.Fatal(err)
	}
	if gotPath != "/agnesapi?video_id=video_456&model_name=agnes-video-v2.0" {
		t.Fatalf("path = %q", gotPath)
	}
}

func TestBindVideoResponseIDsMapsTaskIDToVideoID(t *testing.T) {
	srv, err := NewServer(Config{Providers: []Provider{{
		Name:    "agnes",
		BaseURL: "https://apihub.agnes-ai.com/v1",
		Models: []ModelConfig{{
			Name:             "agnes-video-v2.0",
			Alias:            "agnes-video-v2.0",
			Type:             "video",
			Endpoint:         "/videos",
			RequestFormat:    "agnes-video",
			RetrieveEndpoint: "https://apihub.agnes-ai.com/agnesapi?video_id={video_id}&model_name={model}",
		}},
	}}})
	if err != nil {
		t.Fatal(err)
	}

	route, ok := srv.findModel("agnes-video-v2.0")
	if !ok {
		t.Fatal("model route not found")
	}

	srv.bindVideoResponseIDs([]byte(`{
		"id": "task_123",
		"task_id": "task_123",
		"video_id": "video_456"
	}`), route, time.Hour)

	binding, ok := srv.bindings.get("task_123")
	if !ok {
		t.Fatal("task id binding not found")
	}
	if binding.ModelAlias != "agnes-video-v2.0" {
		t.Fatalf("model alias = %q", binding.ModelAlias)
	}
	if binding.UpstreamID != "video_456" {
		t.Fatalf("upstream id = %q, want video_456", binding.UpstreamID)
	}
	if binding.RouteKey == "" {
		t.Fatal("route key should be bound")
	}
}

func TestFindModelRoundRobinsSameAliasAcrossKeys(t *testing.T) {
	srv, err := NewServer(Config{Providers: []Provider{
		{
			Name:    "agnes",
			BaseURL: "https://apihub.agnes-ai.com/v1",
			APIKey:  "sk-one",
			Models: []ModelConfig{{
				Name:          "agnes-image-2.1-flash",
				Alias:         "agnes-image-2.1-flash",
				Type:          "image",
				Endpoint:      "/images/generations",
				RequestFormat: "agnes-image",
				DefaultSize:   "1024x768",
			}},
		},
		{
			Name:    "agnes",
			BaseURL: "https://apihub.agnes-ai.com/v1",
			APIKey:  "sk-two",
			Models: []ModelConfig{{
				Name:          "agnes-image-2.1-flash",
				Alias:         "agnes-image-2.1-flash",
				Type:          "image",
				Endpoint:      "/images/generations",
				RequestFormat: "agnes-image",
				DefaultSize:   "1024x768",
			}},
		},
	}})
	if err != nil {
		t.Fatal(err)
	}

	first, ok := srv.findModel("agnes-image-2.1-flash")
	if !ok {
		t.Fatal("first route not found")
	}
	second, ok := srv.findModel("agnes-image-2.1-flash")
	if !ok {
		t.Fatal("second route not found")
	}
	third, ok := srv.findModel("agnes-image-2.1-flash")
	if !ok {
		t.Fatal("third route not found")
	}

	if first.Provider.APIKey != "sk-one" {
		t.Fatalf("first key = %q", first.Provider.APIKey)
	}
	if second.Provider.APIKey != "sk-two" {
		t.Fatalf("second key = %q", second.Provider.APIKey)
	}
	if third.Provider.APIKey != "sk-one" {
		t.Fatalf("third key = %q", third.Provider.APIKey)
	}
}

func TestVideoBindingPinsRetrieveToCreateRouteKey(t *testing.T) {
	srv, err := NewServer(Config{Providers: []Provider{
		{
			Name:    "agnes",
			BaseURL: "https://apihub.agnes-ai.com/v1",
			APIKey:  "sk-create",
			Models: []ModelConfig{{
				Name:             "agnes-video-v2.0",
				Alias:            "agnes-video-v2.0",
				Type:             "video",
				Endpoint:         "/videos",
				RequestFormat:    "agnes-video",
				RetrieveEndpoint: "https://apihub.agnes-ai.com/agnesapi?video_id={video_id}&model_name={model}",
			}},
		},
		{
			Name:    "agnes",
			BaseURL: "https://apihub.agnes-ai.com/v1",
			APIKey:  "sk-other",
			Models: []ModelConfig{{
				Name:             "agnes-video-v2.0",
				Alias:            "agnes-video-v2.0",
				Type:             "video",
				Endpoint:         "/videos",
				RequestFormat:    "agnes-video",
				RetrieveEndpoint: "https://apihub.agnes-ai.com/agnesapi?video_id={video_id}&model_name={model}",
			}},
		},
	}})
	if err != nil {
		t.Fatal(err)
	}

	createRoute, ok := srv.findModel("agnes-video-v2.0")
	if !ok {
		t.Fatal("create route not found")
	}
	srv.bindVideoResponseIDs([]byte(`{"task_id":"task_123","video_id":"video_456"}`), createRoute, time.Hour)
	binding, ok := srv.bindings.get("task_123")
	if !ok {
		t.Fatal("binding not found")
	}
	retrieveRoute, ok := srv.findModelWithRouteKey(binding.ModelAlias, binding.RouteKey)
	if !ok {
		t.Fatal("retrieve route not found")
	}
	if retrieveRoute.Provider.APIKey != createRoute.Provider.APIKey {
		t.Fatalf("retrieve key = %q, want %q", retrieveRoute.Provider.APIKey, createRoute.Provider.APIKey)
	}
}

func TestLoadConfigReadsAgnesAuthDir(t *testing.T) {
	dir := t.TempDir()
	authDir := filepath.Join(dir, "auth")
	agnesDir := filepath.Join(authDir, "agnes")
	if err := os.MkdirAll(agnesDir, 0o755); err != nil {
		t.Fatal(err)
	}
	authPayload := `{
		"content": {
			"api_key": "sk-test",
			"base_url": "https://apihub.agnes-ai.com/v1",
			"model": "agnes-2.0-flash",
			"models": ["agnes-2.0-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"],
			"provider": "agnes",
			"type": "api_key"
		},
		"disabled": false
	}`
	if err := os.WriteFile(filepath.Join(agnesDir, "agnes.json"), []byte(authPayload), 0o644); err != nil {
		t.Fatal(err)
	}
	configPath := filepath.Join(dir, "config.json")
	configPayload, _ := json.Marshal(map[string]any{
		"listen":         "127.0.0.1:8320",
		"auth_dir":       authDir,
		"auth_providers": []AuthProviderConfig{testAgnesAuthProviderConfig()},
	})
	if err := os.WriteFile(configPath, configPayload, 0o644); err != nil {
		t.Fatal(err)
	}

	cfg, err := loadConfig(configPath)
	if err != nil {
		t.Fatal(err)
	}
	srv, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	imageRoute, ok := srv.findModel("agnes-image-2.1-flash")
	if !ok {
		t.Fatal("image model route not found")
	}
	if imageRoute.Provider.APIKey != "sk-test" {
		t.Fatalf("api key = %q", imageRoute.Provider.APIKey)
	}
	if imageRoute.Provider.BaseURL != "https://apihub.agnes-ai.com/v1" {
		t.Fatalf("base url = %q", imageRoute.Provider.BaseURL)
	}
	if imageRoute.Model.RequestFormat != "agnes-image" {
		t.Fatalf("image request format = %q", imageRoute.Model.RequestFormat)
	}
	videoRoute, ok := srv.findModel("agnes-video-v2.0")
	if !ok {
		t.Fatal("video model route not found")
	}
	if videoRoute.Model.Endpoint != "/videos" {
		t.Fatalf("video endpoint = %q", videoRoute.Model.Endpoint)
	}
	if videoRoute.Model.RetrieveEndpoint != "https://apihub.agnes-ai.com/agnesapi?video_id={video_id}&model_name={model}" {
		t.Fatalf("video retrieve endpoint = %q", videoRoute.Model.RetrieveEndpoint)
	}
}

func TestAuthProviderRulesSupportOtherVideoProviders(t *testing.T) {
	content := map[string]any{
		"model":    "acme-video-pro",
		"models":   []any{"acme-video-pro"},
		"provider": "acme",
	}
	models := mediaModelsFromAuthContent("acme", "https://media.example.com/api", content, []AuthProviderConfig{{
		Provider: "acme",
		ModelRules: []AuthModelRule{{
			MatchContains:     "video",
			Type:              "video",
			Endpoint:          "/jobs",
			RetrieveEndpoint:  "{base_url}/jobs/{id}",
			Method:            http.MethodPost,
			RequestFormat:     "passthrough",
			PollIntervalMS:    1000,
			PollTimeoutSecond: 60,
		}},
	}})
	if len(models) != 1 {
		t.Fatalf("models = %#v", models)
	}
	got := models[0]
	if got.Name != "acme-video-pro" || got.Type != "video" || got.RequestFormat != "passthrough" {
		t.Fatalf("model = %#v", got)
	}
	if got.RetrieveEndpoint != "https://media.example.com/api/jobs/{id}" {
		t.Fatalf("retrieve endpoint = %q", got.RetrieveEndpoint)
	}
}

func testAgnesAuthProviderConfig() AuthProviderConfig {
	return AuthProviderConfig{
		Provider: "agnes",
		Headers:  map[string]string{"Content-Type": "application/json"},
		ModelRules: []AuthModelRule{
			{
				MatchContains:  "image",
				Type:           "image",
				Endpoint:       "/images/generations",
				Method:         http.MethodPost,
				RequestFormat:  "agnes-image",
				ResponseFormat: "url",
				DefaultSize:    "1024x768",
			},
			{
				MatchContains:     "video",
				Type:              "video",
				Endpoint:          "/videos",
				RetrieveEndpoint:  "{origin}/agnesapi?video_id={video_id}&model_name={model}",
				Method:            http.MethodPost,
				RequestFormat:     "agnes-video",
				ResponseFormat:    "auto",
				PollIntervalMS:    3000,
				PollTimeoutSecond: 180,
			},
		},
	}
}
