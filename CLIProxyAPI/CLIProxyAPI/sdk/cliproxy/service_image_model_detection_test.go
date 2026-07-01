package cliproxy

import (
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
)

func TestIsImageModelName(t *testing.T) {
	imageModels := []string{
		"agnes-image-2.0-flash",
		"agnes-image-2.1-flash",
		"dall-e-3",
		"dalle-2",
		"stable-diffusion-3.5",
		"flux-pro-1.1",
		"cogview-3",
		"recraft-v3",
		"grok-imagine-image",
		"sdxl-lightning",
		"mj-v6",
		"kolors",
		"seedream-1",
	}

	for _, m := range imageModels {
		if !isImageModelName(m) {
			t.Errorf("expected isImageModelName(%q) to be true, got false", m)
		}
	}

	textModels := []string{
		"agnes-2.0-flash",
		"gpt-4o",
		"claude-3-5-sonnet",
		"gemini-1.5-flash",
		"deepseek-chat",
		"qwen-turbo",
	}

	for _, m := range textModels {
		if isImageModelName(m) {
			t.Errorf("expected isImageModelName(%q) to be false, got true", m)
		}
	}
}

func TestBuildFileCompatModels(t *testing.T) {
	inputModels := []string{
		"agnes-2.0-flash",
		"agnes-image-2.0-flash",
		"agnes-video-v2.0",
	}

	models := buildFileCompatModels("agnes", inputModels)
	if len(models) != 3 {
		t.Fatalf("expected 3 models, got %d", len(models))
	}

	// 1. Text model
	if models[0].ID != "agnes-2.0-flash" {
		t.Errorf("expected model[0] ID to be agnes-2.0-flash, got %s", models[0].ID)
	}
	if models[0].Type != "openai-compatibility" {
		t.Errorf("expected model[0] Type to be openai-compatibility, got %s", models[0].Type)
	}

	// 2. Image model (should be auto-detected)
	if models[1].ID != "agnes-image-2.0-flash" {
		t.Errorf("expected model[1] ID to be agnes-image-2.0-flash, got %s", models[1].ID)
	}
	if models[1].Type != registry.OpenAIImageModelType {
		t.Errorf("expected model[1] Type to be %s, got %s", registry.OpenAIImageModelType, models[1].Type)
	}

	// 3. Video model (not auto-detected as image)
	if models[2].ID != "agnes-video-v2.0" {
		t.Errorf("expected model[2] ID to be agnes-video-v2.0, got %s", models[2].ID)
	}
	if models[2].Type != "openai-compatibility" {
		t.Errorf("expected model[2] Type to be openai-compatibility, got %s", models[2].Type)
	}
}

func TestBuildOpenAICompatibilityConfigModels(t *testing.T) {
	compat := &config.OpenAICompatibility{
		Name: "agnes",
		Models: []config.OpenAICompatibilityModel{
			{Name: "agnes-2.0-flash"},
			{Name: "agnes-image-2.0-flash"}, // image: true is not set, should auto-detect
			{Name: "custom-paint-model", Image: true}, // image: true is set explicitly
		},
	}

	models := buildOpenAICompatibilityConfigModels(compat)
	if len(models) != 3 {
		t.Fatalf("expected 3 models, got %d", len(models))
	}

	// 1. Text model
	if models[0].ID != "agnes-2.0-flash" {
		t.Errorf("expected model[0] ID to be agnes-2.0-flash, got %s", models[0].ID)
	}
	if models[0].Type != "openai-compatibility" {
		t.Errorf("expected model[0] Type to be openai-compatibility, got %s", models[0].Type)
	}

	// 2. Image model (auto-detected)
	if models[1].ID != "agnes-image-2.0-flash" {
		t.Errorf("expected model[1] ID to be agnes-image-2.0-flash, got %s", models[1].ID)
	}
	if models[1].Type != registry.OpenAIImageModelType {
		t.Errorf("expected model[1] Type to be %s, got %s", registry.OpenAIImageModelType, models[1].Type)
	}

	// 3. Image model (explicit)
	if models[2].ID != "custom-paint-model" {
		t.Errorf("expected model[2] ID to be custom-paint-model, got %s", models[2].ID)
	}
	if models[2].Type != registry.OpenAIImageModelType {
		t.Errorf("expected model[2] Type to be %s, got %s", registry.OpenAIImageModelType, models[2].Type)
	}
}
