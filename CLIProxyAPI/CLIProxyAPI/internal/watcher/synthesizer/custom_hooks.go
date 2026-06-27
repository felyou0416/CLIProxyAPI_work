package synthesizer

import (
	"strings"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
)

// ApplyCustomApiKeyAttributes populates attributes for custom api_key providers.
func ApplyCustomApiKeyAttributes(a *coreauth.Auth, t string, metadata map[string]any, provider string) {
	if strings.ToLower(t) == "api_key" {
		var apiKey, baseURL string
		if content, ok := metadata["content"].(map[string]any); ok && content != nil {
			if k, ok := content["api_key"].(string); ok && k != "" {
				apiKey = k
			}
			if b, ok := content["base_url"].(string); ok && b != "" {
				baseURL = b
			}
		}
		if apiKey == "" {
			if k, ok := metadata["api_key"].(string); ok && k != "" {
				apiKey = k
			}
		}
		if baseURL == "" {
			if b, ok := metadata["base_url"].(string); ok && b != "" {
				baseURL = b
			}
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
}
