package main

import (
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Enabled      bool           `yaml:"enabled" json:"enabled"`
	Listen       ListenConfig   `yaml:"listen" json:"listen"`
	Upstream     UpstreamConfig `yaml:"upstream" json:"upstream"`
	ClientAuth   ClientAuth     `yaml:"client_auth" json:"client_auth"`
	Routes       []Route        `yaml:"routes" json:"routes"`
	Features     Features       `yaml:"features" json:"features"`
	Thinking     ThinkingConfig `yaml:"thinking" json:"thinking"`
	MaxBodyBytes int64          `yaml:"max_body_bytes" json:"max_body_bytes"`
}

type ListenConfig struct {
	Host string `yaml:"host" json:"host"`
	Port int    `yaml:"port" json:"port"`
}

type UpstreamConfig struct {
	BaseURL               string `yaml:"base_url" json:"base_url"`
	APIKey                string `yaml:"api_key" json:"api_key"`
	ConnectTimeoutSeconds int    `yaml:"connect_timeout_seconds" json:"connect_timeout_seconds"`
	RequestTimeoutSeconds int    `yaml:"request_timeout_seconds" json:"request_timeout_seconds"`
}

type ClientAuth struct {
	APIKeys []string `yaml:"api_keys" json:"api_keys"`
}

type Route struct {
	Alias          string `yaml:"alias" json:"alias"`
	UpstreamModel  string `yaml:"upstream_model" json:"upstream_model"`
	UpstreamFormat string `yaml:"upstream_format" json:"upstream_format"`
}

type Features struct {
	Streaming   bool              `yaml:"streaming" json:"streaming"`
	Tools       bool              `yaml:"tools" json:"tools"`
	Images      bool              `yaml:"images" json:"images"`
	Documents   bool              `yaml:"documents" json:"documents"`
	CountTokens CountTokensConfig `yaml:"count_tokens" json:"count_tokens"`
}

type CountTokensConfig struct {
	Mode string `yaml:"mode" json:"mode"`
}

type ThinkingConfig struct {
	Unsupported string `yaml:"unsupported" json:"unsupported"`
}

func DefaultConfig() Config {
	return Config{
		Enabled: false,
		Listen:  ListenConfig{Host: "127.0.0.1", Port: 8319},
		Upstream: UpstreamConfig{
			BaseURL:               "http://127.0.0.1:8317",
			ConnectTimeoutSeconds: 10,
			RequestTimeoutSeconds: 600,
		},
		Features: Features{
			Streaming:   true,
			Tools:       true,
			Images:      true,
			Documents:   false,
			CountTokens: CountTokensConfig{Mode: "local_estimate"},
		},
		Thinking:     ThinkingConfig{Unsupported: "reject"},
		MaxBodyBytes: 4 << 20,
	}
}

func LoadConfig(path string) (Config, error) {
	config := DefaultConfig()
	raw, err := os.ReadFile(path)
	if err != nil {
		return config, fmt.Errorf("read config: %w", err)
	}
	if err := yaml.Unmarshal(raw, &config); err != nil {
		return config, fmt.Errorf("decode config: %w", err)
	}
	if err := config.Validate(); err != nil {
		return config, err
	}
	return config, nil
}

func (c Config) Validate() error {
	if c.Listen.Host == "" {
		return fmt.Errorf("listen.host is required")
	}
	if c.Listen.Port < 1 || c.Listen.Port > 65535 {
		return fmt.Errorf("listen.port must be between 1 and 65535")
	}
	if c.MaxBodyBytes <= 0 {
		return fmt.Errorf("max_body_bytes must be positive")
	}
	if strings.TrimSpace(c.Upstream.BaseURL) == "" {
		return fmt.Errorf("upstream.base_url is required")
	}
	u, err := url.Parse(c.Upstream.BaseURL)
	if err != nil || u.Scheme == "" || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return fmt.Errorf("upstream.base_url must be an http or https URL")
	}
	if c.Upstream.ConnectTimeoutSeconds < 0 || c.Upstream.RequestTimeoutSeconds < 0 {
		return fmt.Errorf("upstream timeouts cannot be negative")
	}
	if c.Upstream.RequestTimeoutSeconds == 0 {
		return fmt.Errorf("upstream.request_timeout_seconds must be positive")
	}
	if len(c.ClientAuth.APIKeys) == 0 {
		return fmt.Errorf("client_auth.api_keys must contain at least one key")
	}
	seen := map[string]struct{}{}
	for i, key := range c.ClientAuth.APIKeys {
		if strings.TrimSpace(key) == "" {
			return fmt.Errorf("client_auth.api_keys[%d] is empty", i)
		}
		if _, ok := seen[key]; ok {
			return fmt.Errorf("client_auth.api_keys contains duplicate key")
		}
		seen[key] = struct{}{}
	}
	if len(c.Routes) == 0 {
		return fmt.Errorf("routes must contain at least one route")
	}
	aliases := map[string]struct{}{}
	for i, route := range c.Routes {
		alias := strings.TrimSpace(route.Alias)
		model := strings.TrimSpace(route.UpstreamModel)
		if alias == "" || model == "" {
			return fmt.Errorf("routes[%d] requires alias and upstream_model", i)
		}
		if _, ok := aliases[normalizeModel(alias)]; ok {
			return fmt.Errorf("routes contains duplicate alias %q", alias)
		}
		aliases[normalizeModel(alias)] = struct{}{}
		format := strings.TrimSpace(route.UpstreamFormat)
		if format != "" && format != "openai-chat-completions" {
			return fmt.Errorf("routes[%d].upstream_format %q is unsupported", i, format)
		}
	}
	if c.Features.CountTokens.Mode == "" {
		return fmt.Errorf("features.count_tokens.mode is required")
	}
	if c.Features.CountTokens.Mode != "local_estimate" {
		return fmt.Errorf("features.count_tokens.mode %q is unsupported", c.Features.CountTokens.Mode)
	}
	policy := strings.ToLower(strings.TrimSpace(c.Thinking.Unsupported))
	if policy == "" {
		policy = "reject"
	}
	if policy != "reject" && policy != "strip" {
		return fmt.Errorf("thinking.unsupported must be reject or strip")
	}
	return nil
}

func (c Config) Address() string {
	return net.JoinHostPort(c.Listen.Host, strconv.Itoa(c.Listen.Port))
}

func (c Config) RouteFor(model string) (Route, bool) {
	wanted := normalizeModel(model)
	for _, route := range c.Routes {
		if normalizeModel(route.Alias) == wanted {
			return route, true
		}
	}
	return Route{}, false
}

func normalizeModel(value string) string {
	return strings.ToLower(strings.TrimSpace(strings.TrimPrefix(value, "models/")))
}

func resolveConfigPath(path string) string {
	if path == "" {
		return "claude-adapter.yaml"
	}
	absolute, err := filepath.Abs(path)
	if err == nil {
		return absolute
	}
	return path
}
