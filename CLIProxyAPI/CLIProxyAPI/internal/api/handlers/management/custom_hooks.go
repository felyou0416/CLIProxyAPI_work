package management

import (
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
)

// PromoteNestedContent promotes nested "content" values to the root level.
func PromoteNestedContent(data map[string]any) map[string]any {
	if data == nil {
		return nil
	}
	if content, ok := data["content"].(map[string]any); ok && content != nil {
		for k, v := range content {
			if _, exists := data[k]; !exists {
				data[k] = v
			}
		}
	}
	return data
}

// ApplyAuthFileCustomApiKeyAttributes populates attributes for custom api_key files.
func ApplyAuthFileCustomApiKeyAttributes(a *coreauth.Auth, provider string, data map[string]any) {
	var apiKey, baseURL string
	if k, ok := data["api_key"].(string); ok && k != "" {
		apiKey = k
	}
	if b, ok := data["base_url"].(string); ok && b != "" {
		baseURL = b
	}
	if apiKey != "" {
		a.Attributes["api_key"] = apiKey
	}
	if baseURL != "" {
		a.Attributes["base_url"] = baseURL
	}
	a.Attributes["compat_name"] = provider
	a.Attributes["provider_key"] = provider
}
