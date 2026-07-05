package thinking

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestConfigLoaderAndResolution(t *testing.T) {
	// Create temp storage directory
	tempDir, err := os.MkdirTemp(t.TempDir(), "storage")
	if err != nil {
		t.Fatalf("failed to create temp storage: %v", err)
	}

	SetStorageDir(tempDir)
	defer SetStorageDir("")

	modelsDir := filepath.Join(tempDir, "models")
	if err := os.MkdirAll(modelsDir, 0755); err != nil {
		t.Fatalf("failed to create models dir: %v", err)
	}

	configsPath := filepath.Join(modelsDir, "model_thinking_configs.json")

	// Helper to write config file
	writeMockConfigs := func(configs map[string]modelThinkingConfigEntry) {
		payload := modelThinkingConfigsFile{
			Version:   1,
			UpdatedAt: time.Now().Unix(),
			Configs:   configs,
		}
		data, err := json.MarshalIndent(payload, "", "  ")
		if err != nil {
			t.Fatalf("failed to marshal configs: %v", err)
		}
		if err := os.WriteFile(configsPath, data, 0644); err != nil {
			t.Fatalf("failed to write configs file: %v", err)
		}
	}

	// 1. Write initial configs
	budget2048 := 2048
	writeMockConfigs(map[string]modelThinkingConfigEntry{
		"claude-3-5-sonnet": {
			Mode:            "force_off",
			ReasoningEffort: "",
			ThinkingBudget:  nil,
		},
		"gemini-2.5-pro": {
			Mode:            "force_on",
			ReasoningEffort: "",
			ThinkingBudget:  &budget2048,
		},
		"gemini-2.5-flash": {
			Mode:            "force_on",
			ReasoningEffort: "medium",
			ThinkingBudget:  nil,
		},
		"o1-mini": {
			Mode:            "default",
			ReasoningEffort: "low",
			ThinkingBudget:  nil,
		},
	})

	// Test cache invalidation and loadConfigs
	loaded := loadConfigs()
	if loaded == nil {
		t.Fatalf("loadConfigs returned nil")
	}

	// Test force_off resolution
	res := resolveEffectiveConfig([]byte(`{}`), "claude-3-5-sonnet", "claude", "claude", SuffixResult{ModelName: "claude-3-5-sonnet", HasSuffix: false})
	if res.Mode != ModeNone || res.Budget != 0 {
		t.Errorf("expected ModeNone, got Mode %v, Budget %d", res.Mode, res.Budget)
	}

	// Test suffix overriding force_off
	res = resolveEffectiveConfig([]byte(`{}`), "claude-3-5-sonnet(high)", "claude", "claude", SuffixResult{ModelName: "claude-3-5-sonnet", HasSuffix: true, RawSuffix: "high"})
	if res.Mode != ModeLevel || res.Level != LevelHigh {
		t.Errorf("expected ModeLevel/high via suffix, got Mode %v, Level %v", res.Mode, res.Level)
	}

	// Test force_on with budget resolution
	res = resolveEffectiveConfig([]byte(`{}`), "gemini-2.5-pro", "gemini", "gemini", SuffixResult{ModelName: "gemini-2.5-pro", HasSuffix: false})
	if res.Mode != ModeBudget || res.Budget != 2048 {
		t.Errorf("expected ModeBudget/2048, got Mode %v, Budget %d", res.Mode, res.Budget)
	}

	// Test force_on with effort resolution
	res = resolveEffectiveConfig([]byte(`{}`), "gemini-2.5-flash", "gemini", "gemini", SuffixResult{ModelName: "gemini-2.5-flash", HasSuffix: false})
	if res.Mode != ModeLevel || res.Level != "medium" {
		t.Errorf("expected ModeLevel/medium, got Mode %v, Level %s", res.Mode, res.Level)
	}

	// Test default mode: falls back to custom config default when request body has no config
	res = resolveEffectiveConfig([]byte(`{}`), "o1-mini", "openai", "openai", SuffixResult{ModelName: "o1-mini", HasSuffix: false})
	if res.Mode != ModeLevel || res.Level != "low" {
		t.Errorf("expected fallback to custom config default (low), got Mode %v, Level %s", res.Mode, res.Level)
	}

	// Test default mode: respects request body config when present
	openaiBodyWithHighEffort := []byte(`{"reasoning_effort":"high"}`)
	res = resolveEffectiveConfig(openaiBodyWithHighEffort, "o1-mini", "openai", "openai", SuffixResult{ModelName: "o1-mini", HasSuffix: false})
	if res.Mode != ModeLevel || res.Level != "high" {
		t.Errorf("expected request body config to take precedence, got Mode %v, Level %s", res.Mode, res.Level)
	}

	// Test case insensitivity lookup
	res = resolveEffectiveConfig([]byte(`{}`), "CLAUDE-3-5-SONNET", "claude", "claude", SuffixResult{ModelName: "CLAUDE-3-5-SONNET", HasSuffix: false})
	if res.Mode != ModeNone || res.Budget != 0 {
		t.Errorf("expected case-insensitive lookup to find force_off, got Mode %v, Budget %d", res.Mode, res.Budget)
	}

	// 2. Modify config file and check cache reload/invalidation
	// We sleep slightly to make sure file modification time is strictly newer
	time.Sleep(10 * time.Millisecond)
	writeMockConfigs(map[string]modelThinkingConfigEntry{
		"claude-3-5-sonnet": {
			Mode:            "force_on",
			ReasoningEffort: "high",
			ThinkingBudget:  nil,
		},
	})

	// This should load the modified config
	res = resolveEffectiveConfig([]byte(`{}`), "claude-3-5-sonnet", "claude", "claude", SuffixResult{ModelName: "claude-3-5-sonnet", HasSuffix: false})
	if res.Mode != ModeLevel || res.Level != LevelHigh {
		t.Errorf("expected cache update to load force_on/high, got Mode %v, Level %s", res.Mode, res.Level)
	}
}
