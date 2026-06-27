package cliproxy

import (
	"strings"
	"time"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
)

// TryRegisterModelsFromMetadata registers compat models directly from metadata.
func (s *Service) TryRegisterModelsFromMetadata(a *coreauth.Auth, providerKey, compatName string) bool {
	fileModelNames := extractModelsFromMetadata(a.Metadata)
	if len(fileModelNames) > 0 {
		ms := buildFileCompatModels(compatName, fileModelNames)
		if len(ms) > 0 {
			if providerKey == "" {
				providerKey = "openai-compatibility"
			}
			s.registerResolvedModelsForAuth(a, providerKey, applyModelPrefixes(ms, a.Prefix, s.cfg.ForceModelPrefix))
			return true
		}
	}
	return false
}

func extractModelsFromMetadata(metadata map[string]any) []string {
	if metadata == nil {
		return nil
	}
	content, _ := metadata["content"].(map[string]any)
	if content == nil {
		content = metadata
	}
	var rawModels any
	if m, ok := content["models"]; ok {
		rawModels = m
	} else if m, ok := content["model"]; ok {
		rawModels = m
	}
	if rawModels == nil {
		return nil
	}
	switch v := rawModels.(type) {
	case string:
		if trimmed := strings.TrimSpace(v); trimmed != "" {
			return []string{trimmed}
		}
	case []string:
		return v
	case []any:
		res := make([]string, 0, len(v))
		for _, item := range v {
			if s, ok := item.(string); ok {
				if trimmed := strings.TrimSpace(s); trimmed != "" {
					res = append(res, trimmed)
				}
			}
		}
		return res
	}
	return nil
}

func buildFileCompatModels(providerName string, modelNames []string) []*ModelInfo {
	if len(modelNames) == 0 {
		return nil
	}
	now := time.Now().Unix()
	models := make([]*ModelInfo, 0, len(modelNames))
	for _, mName := range modelNames {
		modelID := strings.TrimSpace(mName)
		if modelID == "" {
			continue
		}
		modelType := "openai-compatibility"
		thinking := &registry.ThinkingSupport{Levels: []string{"low", "medium", "high"}}
		models = append(models, &ModelInfo{
			ID:          modelID,
			Object:      "model",
			Created:     now,
			OwnedBy:     providerName,
			Type:        modelType,
			DisplayName: modelID,
			Version:     modelID,
			UserDefined: false,
			Thinking:    thinking,
		})
	}
	return models
}
