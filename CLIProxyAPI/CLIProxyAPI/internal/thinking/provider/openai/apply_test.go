package openai

import (
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/thinking"
	"github.com/tidwall/gjson"
)

func TestApplyCompatibleOpenAI_AgnesUsesChatTemplateKwargs(t *testing.T) {
	applier := NewApplier()
	body := []byte(`{"model":"agnes-2.0-flash","messages":[],"reasoning_effort":"high"}`)

	got, err := applier.Apply(body, thinking.ThinkingConfig{Mode: thinking.ModeAuto, Budget: -1}, nil)
	if err != nil {
		t.Fatalf("Apply returned error: %v", err)
	}

	if enabled := gjson.GetBytes(got, "chat_template_kwargs.enable_thinking"); !enabled.Exists() || !enabled.Bool() {
		t.Fatalf("enable_thinking = %s, want true; body=%s", enabled.Raw, string(got))
	}
	if gjson.GetBytes(got, "reasoning_effort").Exists() {
		t.Fatalf("reasoning_effort should be removed for Agnes OpenAI-compatible thinking: %s", string(got))
	}
}

func TestApplyCompatibleOpenAI_AgnesForceOffDisablesChatTemplateKwargs(t *testing.T) {
	applier := NewApplier()
	body := []byte(`{"model":"agnes-2.0-flash","messages":[],"chat_template_kwargs":{"enable_thinking":true}}`)

	got, err := applier.Apply(body, thinking.ThinkingConfig{Mode: thinking.ModeNone, Budget: 0}, nil)
	if err != nil {
		t.Fatalf("Apply returned error: %v", err)
	}

	if enabled := gjson.GetBytes(got, "chat_template_kwargs.enable_thinking"); !enabled.Exists() || enabled.Bool() {
		t.Fatalf("enable_thinking = %s, want false; body=%s", enabled.Raw, string(got))
	}
}

func TestApplyCompatibleOpenAI_NonAgnesKeepsReasoningEffort(t *testing.T) {
	applier := NewApplier()
	body := []byte(`{"model":"o1-mini","messages":[]}`)

	got, err := applier.Apply(body, thinking.ThinkingConfig{Mode: thinking.ModeLevel, Level: thinking.LevelHigh}, &registry.ModelInfo{ID: "o1-mini", UserDefined: true})
	if err != nil {
		t.Fatalf("Apply returned error: %v", err)
	}

	if effort := gjson.GetBytes(got, "reasoning_effort").String(); effort != "high" {
		t.Fatalf("reasoning_effort = %q, want high; body=%s", effort, string(got))
	}
	if gjson.GetBytes(got, "chat_template_kwargs.enable_thinking").Exists() {
		t.Fatalf("enable_thinking should not be set for regular OpenAI models: %s", string(got))
	}
}
