package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

func TestRouteConfiguredMediaModel(t *testing.T) {
	state.Lock()
	state.config = defaultConfig()
	state.Unlock()
	raw, errMarshal := json.Marshal(pluginapi.ModelRouteRequest{
		RequestedModel:     "agnes-agnes-video-v2.0",
		AvailableProviders: []string{"openai-compatible-agnes-media"},
	})
	if errMarshal != nil {
		t.Fatal(errMarshal)
	}
	response, errRoute := routeModel(raw)
	if errRoute != nil {
		t.Fatal(errRoute)
	}
	var env envelope
	if errUnmarshal := json.Unmarshal(response, &env); errUnmarshal != nil {
		t.Fatal(errUnmarshal)
	}
	var result pluginapi.ModelRouteResponse
	if errUnmarshal := json.Unmarshal(env.Result, &result); errUnmarshal != nil {
		t.Fatal(errUnmarshal)
	}
	if !result.Handled || result.Target != "openai-compatible-agnes-media" {
		t.Fatalf("route = %#v", result)
	}
}

func TestInterceptAgnesThinkingFromRequest(t *testing.T) {
	raw, errMarshal := json.Marshal(pluginapi.RequestInterceptRequest{
		Model:          "agnes-2.0-flash",
		RequestedModel: "agnes-agnes-2.0-flash",
		Body:           []byte(`{"model":"agnes-2.0-flash","reasoning_effort":"high"}`),
	})
	if errMarshal != nil {
		t.Fatal(errMarshal)
	}
	response, errIntercept := interceptAfterAuth(raw)
	if errIntercept != nil {
		t.Fatal(errIntercept)
	}
	var env envelope
	if errUnmarshal := json.Unmarshal(response, &env); errUnmarshal != nil {
		t.Fatal(errUnmarshal)
	}
	var result pluginapi.RequestInterceptResponse
	if errUnmarshal := json.Unmarshal(env.Result, &result); errUnmarshal != nil {
		t.Fatal(errUnmarshal)
	}
	var body map[string]any
	if errUnmarshal := json.Unmarshal(result.Body, &body); errUnmarshal != nil {
		t.Fatal(errUnmarshal)
	}
	if _, exists := body["reasoning_effort"]; exists {
		t.Fatal("reasoning_effort was not removed")
	}
	kwargs, _ := body["chat_template_kwargs"].(map[string]any)
	if kwargs["enable_thinking"] != true {
		t.Fatalf("chat_template_kwargs = %#v", kwargs)
	}
}

func TestThinkingConfigForceOff(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "thinking.json")
	if errWrite := os.WriteFile(path, []byte(`{"configs":{"agnes-agnes-2.0-flash":{"mode":"force_off"}}}`), 0o600); errWrite != nil {
		t.Fatal(errWrite)
	}
	state.Lock()
	config := defaultConfig()
	config.ThinkingConfigFile = path
	state.config = config
	state.Unlock()

	decision, decided := thinkingDecision(pluginapi.RequestInterceptRequest{
		Model:          "agnes-2.0-flash",
		RequestedModel: "agnes-agnes-2.0-flash",
		Body:           []byte(`{"reasoning_effort":"high"}`),
	})
	if !decided || decision {
		t.Fatalf("decision = %v, decided = %v", decision, decided)
	}
}
