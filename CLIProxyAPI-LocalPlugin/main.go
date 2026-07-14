package main

/*
#include <stdint.h>
#include <stdlib.h>

typedef struct {
	void* ptr;
	size_t len;
} cliproxy_buffer;

typedef int (*cliproxy_host_call_fn)(void*, const char*, const uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_host_free_fn)(void*, size_t);

typedef struct {
	uint32_t abi_version;
	void* host_ctx;
	cliproxy_host_call_fn call;
	cliproxy_host_free_fn free_buffer;
} cliproxy_host_api;

typedef int (*cliproxy_plugin_call_fn)(char*, uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_plugin_free_fn)(void*, size_t);
typedef void (*cliproxy_plugin_shutdown_fn)(void);

typedef struct {
	uint32_t abi_version;
	cliproxy_plugin_call_fn call;
	cliproxy_plugin_free_fn free_buffer;
	cliproxy_plugin_shutdown_fn shutdown;
} cliproxy_plugin_api;

extern int cliproxyPluginCall(char*, uint8_t*, size_t, cliproxy_buffer*);
extern void cliproxyPluginFree(void*, size_t);
extern void cliproxyPluginShutdown(void);
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"unsafe"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginabi"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
	"gopkg.in/yaml.v3"
)

const pluginID = "cliproxy-local"

type envelope struct {
	OK     bool            `json:"ok"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *envelopeError  `json:"error,omitempty"`
}

type envelopeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type lifecycleRequest struct {
	ConfigYAML []byte `json:"config_yaml"`
}

type registration struct {
	SchemaVersion uint32                   `json:"schema_version"`
	Metadata      pluginapi.Metadata       `json:"metadata"`
	Capabilities  registrationCapabilities `json:"capabilities"`
}

type registrationCapabilities struct {
	ModelRouter        bool `json:"model_router"`
	RequestInterceptor bool `json:"request_interceptor"`
	ManagementAPI      bool `json:"management_api"`
}

type managementRegistrationResponse struct {
	Resources []pluginapi.ResourceRoute `json:"resources,omitempty"`
}

type pluginConfig struct {
	ThinkingConfigFile string   `yaml:"thinking_config_file"`
	MediaProvider      string   `yaml:"media_provider"`
	MediaModels        []string `yaml:"media_models"`
}

type thinkingConfigEntry struct {
	Mode            string `json:"mode"`
	ReasoningEffort string `json:"reasoning_effort"`
	ThinkingBudget  *int   `json:"thinking_budget"`
}

type thinkingConfigFile struct {
	Configs map[string]thinkingConfigEntry `json:"configs"`
}

var state = struct {
	sync.RWMutex
	config pluginConfig
}{config: defaultConfig()}

func main() {}

//export cliproxy_plugin_init
func cliproxy_plugin_init(_ *C.cliproxy_host_api, plugin *C.cliproxy_plugin_api) C.int {
	if plugin == nil {
		return 1
	}
	plugin.abi_version = C.uint32_t(pluginabi.ABIVersion)
	plugin.call = C.cliproxy_plugin_call_fn(C.cliproxyPluginCall)
	plugin.free_buffer = C.cliproxy_plugin_free_fn(C.cliproxyPluginFree)
	plugin.shutdown = C.cliproxy_plugin_shutdown_fn(C.cliproxyPluginShutdown)
	return 0
}

//export cliproxyPluginCall
func cliproxyPluginCall(method *C.char, request *C.uint8_t, requestLen C.size_t, response *C.cliproxy_buffer) C.int {
	if response != nil {
		response.ptr = nil
		response.len = 0
	}
	if method == nil {
		writeResponse(response, errorEnvelope("invalid_method", "method is required"))
		return 1
	}
	var rawRequest []byte
	if request != nil && requestLen > 0 {
		rawRequest = C.GoBytes(unsafe.Pointer(request), C.int(requestLen))
	}
	raw, errHandle := handleMethod(C.GoString(method), rawRequest)
	if errHandle != nil {
		writeResponse(response, errorEnvelope("plugin_error", errHandle.Error()))
		return 1
	}
	writeResponse(response, raw)
	return 0
}

//export cliproxyPluginFree
func cliproxyPluginFree(ptr unsafe.Pointer, _ C.size_t) {
	if ptr != nil {
		C.free(ptr)
	}
}

//export cliproxyPluginShutdown
func cliproxyPluginShutdown() {}

func handleMethod(method string, request []byte) ([]byte, error) {
	switch method {
	case pluginabi.MethodPluginRegister, pluginabi.MethodPluginReconfigure:
		if errApply := applyConfig(request); errApply != nil {
			return nil, errApply
		}
		return okEnvelope(pluginRegistration())
	case pluginabi.MethodModelRoute:
		return routeModel(request)
	case pluginabi.MethodRequestInterceptBefore:
		return okEnvelope(pluginapi.RequestInterceptResponse{})
	case pluginabi.MethodRequestInterceptAfter:
		return interceptAfterAuth(request)
	case pluginabi.MethodManagementRegister:
		return okEnvelope(managementRegistrationResponse{Resources: []pluginapi.ResourceRoute{{
			Path:        "/status",
			Menu:        "Local Extensions",
			Description: "Shows local plugin routing and thinking configuration.",
		}}})
	case pluginabi.MethodManagementHandle:
		return managementStatus()
	default:
		return errorEnvelope("unknown_method", "unknown method: "+method), nil
	}
}

func pluginRegistration() registration {
	return registration{
		SchemaVersion: pluginabi.SchemaVersion,
		Metadata: pluginapi.Metadata{
			Name:             "CLIProxyAPI Local Extensions",
			Version:          "0.1.0",
			Author:           "youqu117",
			GitHubRepository: "https://github.com/youqu117/CLIProxyAPI_work",
			ConfigFields: []pluginapi.ConfigField{
				{Name: "thinking_config_file", Type: pluginapi.ConfigFieldTypeString, Description: "Path to Dashboard model thinking configuration."},
				{Name: "media_provider", Type: pluginapi.ConfigFieldTypeString, Description: "CPA provider key used for media models."},
				{Name: "media_models", Type: pluginapi.ConfigFieldTypeArray, Description: "Model IDs routed to MediaProxy."},
			},
		},
		Capabilities: registrationCapabilities{
			ModelRouter:        true,
			RequestInterceptor: true,
			ManagementAPI:      true,
		},
	}
}

func defaultConfig() pluginConfig {
	return pluginConfig{
		MediaProvider: "openai-compatible-agnes-media",
		MediaModels: []string{
			"agnes-image-2.0-flash",
			"agnes-image-2.1-flash",
			"agnes-video-v2.0",
			"agnes-agnes-image-2.0-flash",
			"agnes-agnes-image-2.1-flash",
			"agnes-agnes-video-v2.0",
		},
	}
}

func applyConfig(raw []byte) error {
	var request lifecycleRequest
	if len(raw) > 0 {
		if errUnmarshal := json.Unmarshal(raw, &request); errUnmarshal != nil {
			return fmt.Errorf("decode lifecycle request: %w", errUnmarshal)
		}
	}
	config := defaultConfig()
	if len(request.ConfigYAML) > 0 {
		if errUnmarshal := yaml.Unmarshal(request.ConfigYAML, &config); errUnmarshal != nil {
			return fmt.Errorf("decode plugin config: %w", errUnmarshal)
		}
	}
	if strings.TrimSpace(config.MediaProvider) == "" {
		config.MediaProvider = defaultConfig().MediaProvider
	}
	if len(config.MediaModels) == 0 {
		config.MediaModels = defaultConfig().MediaModels
	}
	state.Lock()
	state.config = config
	state.Unlock()
	return nil
}

func currentConfig() pluginConfig {
	state.RLock()
	defer state.RUnlock()
	config := state.config
	config.MediaModels = append([]string(nil), config.MediaModels...)
	return config
}

func routeModel(raw []byte) ([]byte, error) {
	var request pluginapi.ModelRouteRequest
	if errUnmarshal := json.Unmarshal(raw, &request); errUnmarshal != nil {
		return nil, fmt.Errorf("decode model route request: %w", errUnmarshal)
	}
	config := currentConfig()
	if !containsFold(config.MediaModels, request.RequestedModel) {
		return okEnvelope(pluginapi.ModelRouteResponse{})
	}
	provider := strings.TrimSpace(config.MediaProvider)
	if provider == "" || !containsFold(request.AvailableProviders, provider) {
		return okEnvelope(pluginapi.ModelRouteResponse{})
	}
	return okEnvelope(pluginapi.ModelRouteResponse{
		Handled:     true,
		TargetKind:  pluginapi.ModelRouteTargetProvider,
		Target:      provider,
		TargetModel: request.RequestedModel,
		Reason:      "local media model",
	})
}

func interceptAfterAuth(raw []byte) ([]byte, error) {
	var request pluginapi.RequestInterceptRequest
	if errUnmarshal := json.Unmarshal(raw, &request); errUnmarshal != nil {
		return nil, fmt.Errorf("decode request interceptor payload: %w", errUnmarshal)
	}
	if !isAgnesThinkingModel(request.Model) && !isAgnesThinkingModel(request.RequestedModel) {
		return okEnvelope(pluginapi.RequestInterceptResponse{})
	}
	enabled, decided := thinkingDecision(request)
	if !decided {
		return okEnvelope(pluginapi.RequestInterceptResponse{})
	}
	body, errRewrite := rewriteAgnesThinking(request.Body, enabled)
	if errRewrite != nil {
		return nil, errRewrite
	}
	return okEnvelope(pluginapi.RequestInterceptResponse{Body: body})
}

func thinkingDecision(request pluginapi.RequestInterceptRequest) (bool, bool) {
	config := currentConfig()
	entries := loadThinkingConfigs(config.ThinkingConfigFile)
	for _, model := range []string{request.RequestedModel, request.Model} {
		entry, ok := entries[strings.ToLower(strings.TrimSpace(model))]
		if !ok {
			continue
		}
		switch strings.ToLower(strings.TrimSpace(entry.Mode)) {
		case "force_off":
			return false, true
		case "force_on":
			return true, true
		case "default":
			if strings.TrimSpace(entry.ReasoningEffort) != "" || entry.ThinkingBudget != nil {
				return true, true
			}
		}
	}

	var body map[string]any
	if errUnmarshal := json.Unmarshal(request.Body, &body); errUnmarshal != nil {
		return false, false
	}
	if kwargs, ok := body["chat_template_kwargs"].(map[string]any); ok {
		if enabled, okBool := kwargs["enable_thinking"].(bool); okBool {
			return enabled, true
		}
	}
	if rawEffort, exists := body["reasoning_effort"]; exists {
		effort := strings.ToLower(strings.TrimSpace(fmt.Sprint(rawEffort)))
		return effort != "" && effort != "none" && effort != "off" && effort != "false", true
	}
	if reasoning, ok := body["reasoning"].(map[string]any); ok {
		if rawEffort, exists := reasoning["effort"]; exists {
			effort := strings.ToLower(strings.TrimSpace(fmt.Sprint(rawEffort)))
			return effort != "" && effort != "none" && effort != "off" && effort != "false", true
		}
	}
	return false, false
}

func rewriteAgnesThinking(raw []byte, enabled bool) ([]byte, error) {
	body := make(map[string]any)
	if len(raw) > 0 {
		if errUnmarshal := json.Unmarshal(raw, &body); errUnmarshal != nil {
			return nil, fmt.Errorf("decode Agnes request body: %w", errUnmarshal)
		}
	}
	delete(body, "reasoning_effort")
	if reasoning, ok := body["reasoning"].(map[string]any); ok {
		delete(reasoning, "effort")
		if len(reasoning) == 0 {
			delete(body, "reasoning")
		}
	}
	kwargs, _ := body["chat_template_kwargs"].(map[string]any)
	if kwargs == nil {
		kwargs = make(map[string]any)
		body["chat_template_kwargs"] = kwargs
	}
	kwargs["enable_thinking"] = enabled
	out, errMarshal := json.Marshal(body)
	if errMarshal != nil {
		return nil, fmt.Errorf("encode Agnes request body: %w", errMarshal)
	}
	return out, nil
}

func loadThinkingConfigs(configuredPath string) map[string]thinkingConfigEntry {
	path := strings.TrimSpace(configuredPath)
	if path == "" {
		if storage := strings.TrimSpace(os.Getenv("CLIPROXYAPI_STORAGE_DIR")); storage != "" {
			path = filepath.Join(storage, "models", "model_thinking_configs.json")
		}
	}
	if path == "" {
		return nil
	}
	raw, errRead := os.ReadFile(path)
	if errRead != nil {
		return nil
	}
	var file thinkingConfigFile
	if errUnmarshal := json.Unmarshal(raw, &file); errUnmarshal != nil {
		return nil
	}
	entries := make(map[string]thinkingConfigEntry, len(file.Configs))
	for model, entry := range file.Configs {
		entries[strings.ToLower(strings.TrimSpace(model))] = entry
	}
	return entries
}

func managementStatus() ([]byte, error) {
	config := currentConfig()
	body, errMarshal := json.Marshal(map[string]any{
		"plugin":               pluginID,
		"version":              "0.1.0",
		"media_provider":       config.MediaProvider,
		"media_models":         config.MediaModels,
		"thinking_config_file": config.ThinkingConfigFile,
	})
	if errMarshal != nil {
		return nil, errMarshal
	}
	return okEnvelope(pluginapi.ManagementResponse{
		StatusCode: http.StatusOK,
		Headers:    http.Header{"Content-Type": []string{"application/json"}},
		Body:       body,
	})
}

func isAgnesThinkingModel(model string) bool {
	return strings.Contains(strings.ToLower(strings.TrimSpace(model)), "agnes-2.0-flash")
}

func containsFold(values []string, wanted string) bool {
	wanted = strings.TrimSpace(wanted)
	for _, value := range values {
		if strings.EqualFold(strings.TrimSpace(value), wanted) {
			return true
		}
	}
	return false
}

func okEnvelope(value any) ([]byte, error) {
	raw, errMarshal := json.Marshal(value)
	if errMarshal != nil {
		return nil, errMarshal
	}
	return json.Marshal(envelope{OK: true, Result: raw})
}

func errorEnvelope(code, message string) []byte {
	raw, _ := json.Marshal(envelope{OK: false, Error: &envelopeError{Code: code, Message: message}})
	return raw
}

func writeResponse(response *C.cliproxy_buffer, raw []byte) {
	if response == nil || len(raw) == 0 {
		return
	}
	ptr := C.CBytes(raw)
	if ptr == nil {
		return
	}
	response.ptr = ptr
	response.len = C.size_t(len(raw))
}
