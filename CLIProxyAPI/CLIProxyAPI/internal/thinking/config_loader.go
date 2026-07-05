package thinking

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"
)

type modelThinkingConfigEntry struct {
	Mode            string `json:"mode"`
	ReasoningEffort string `json:"reasoning_effort"`
	ThinkingBudget  *int   `json:"thinking_budget"`
}

type modelThinkingConfigsFile struct {
	Version   int                                 `json:"version"`
	UpdatedAt int64                               `json:"updated_at"`
	Configs   map[string]modelThinkingConfigEntry `json:"configs"`
}

var (
	storageDir     string
	storageDirMu   sync.RWMutex
	configsCache   map[string]modelThinkingConfigEntry
	cacheLastRead  time.Time
	cacheFileMTime time.Time
	cacheMu        sync.Mutex
)

// SetStorageDir sets the base storage directory for looking up model_thinking_configs.json.
func SetStorageDir(dir string) {
	storageDirMu.Lock()
	defer storageDirMu.Unlock()
	storageDir = dir
}

func getStorageDir() string {
	storageDirMu.RLock()
	defer storageDirMu.RUnlock()
	return storageDir
}

func resolveConfigsPath() string {
	dir := getStorageDir()
	if dir != "" {
		return filepath.Join(dir, "models", "model_thinking_configs.json")
	}

	// Fallback check: environment variables
	if envDir := os.Getenv("CLIPROXYAPI_STORAGE_DIR"); envDir != "" {
		return filepath.Join(envDir, "models", "model_thinking_configs.json")
	}
	if envDir := os.Getenv("RELAYX_STORAGE_DIR"); envDir != "" {
		return filepath.Join(envDir, "models", "model_thinking_configs.json")
	}

	// Try relative to current working dir
	p := filepath.Join("storage", "models", "model_thinking_configs.json")
	if _, err := os.Stat(p); err == nil {
		return p
	}

	// Try relative to parent dir (in case running from cmd/server or similar)
	p = filepath.Join("..", "storage", "models", "model_thinking_configs.json")
	if _, err := os.Stat(p); err == nil {
		return p
	}

	// Try home dir fallback
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".cli-proxy-api", "models", "model_thinking_configs.json")
	}

	return ""
}

func loadConfigs() map[string]modelThinkingConfigEntry {
	path := resolveConfigsPath()
	if path == "" {
		return nil
	}

	stat, err := os.Stat(path)
	if err != nil {
		return nil
	}

	cacheMu.Lock()
	defer cacheMu.Unlock()

	// If file has not been modified since our last read, return cached copy
	if stat.ModTime().Equal(cacheFileMTime) && configsCache != nil {
		return configsCache
	}

	data, err := os.ReadFile(path)
	if err != nil {
		log.Warnf("thinking: failed to read configs file %s: %v", path, err)
		return configsCache
	}

	var file modelThinkingConfigsFile
	if err := json.Unmarshal(data, &file); err != nil {
		log.Warnf("thinking: failed to parse configs file %s: %v", path, err)
		return configsCache
	}

	newCache := make(map[string]modelThinkingConfigEntry)
	for k, v := range file.Configs {
		newCache[strings.ToLower(k)] = v
	}

	configsCache = newCache
	cacheFileMTime = stat.ModTime()
	cacheLastRead = time.Now()

	return configsCache
}

// resolveEffectiveConfig determines the unified ThinkingConfig based on suffix, custom config file, and request body.
func resolveEffectiveConfig(body []byte, model string, fromFormat, toFormat string, suffixResult SuffixResult) ThinkingConfig {
	// 1. Suffix priority
	if suffixResult.HasSuffix {
		config := parseSuffixToConfig(suffixResult.RawSuffix, toFormat, model)
		log.WithFields(log.Fields{
			"provider": toFormat,
			"model":    model,
			"mode":     config.Mode,
			"budget":   config.Budget,
			"level":    config.Level,
		}).Debug("thinking: config from model suffix |")
		return config
	}

	// 2. Load custom config from model_thinking_configs.json
	configs := loadConfigs()
	var customEntry modelThinkingConfigEntry
	var hasCustom bool
	if configs != nil {
		customEntry, hasCustom = configs[strings.ToLower(suffixResult.ModelName)]
	}

	// 3. Extract config from request body
	bodyConfig := extractThinkingConfig(body, fromFormat)
	if !hasThinkingConfig(bodyConfig) && fromFormat != toFormat {
		bodyConfig = extractThinkingConfig(body, toFormat)
	}

	if hasCustom {
		switch customEntry.Mode {
		case "force_off":
			log.WithFields(log.Fields{
				"model":    suffixResult.ModelName,
				"provider": toFormat,
			}).Debug("thinking: forced off via thinking configs |")
			return ThinkingConfig{Mode: ModeNone, Budget: 0}

		case "force_on":
			var config ThinkingConfig
			if customEntry.ThinkingBudget != nil {
				config = ThinkingConfig{Mode: ModeBudget, Budget: *customEntry.ThinkingBudget}
			} else if customEntry.ReasoningEffort != "" {
				config = ThinkingConfig{Mode: ModeLevel, Level: ThinkingLevel(customEntry.ReasoningEffort)}
			} else {
				config = ThinkingConfig{Mode: ModeAuto, Budget: -1}
			}
			log.WithFields(log.Fields{
				"model":    suffixResult.ModelName,
				"provider": toFormat,
				"mode":     config.Mode,
				"budget":   config.Budget,
				"level":    config.Level,
			}).Debug("thinking: forced on via thinking configs |")
			return config

		case "default":
			if hasThinkingConfig(bodyConfig) {
				log.WithFields(log.Fields{
					"model":    suffixResult.ModelName,
					"provider": toFormat,
					"mode":     bodyConfig.Mode,
					"budget":   bodyConfig.Budget,
					"level":    bodyConfig.Level,
				}).Debug("thinking: using request body config (custom config is default) |")
				return bodyConfig
			}
			var config ThinkingConfig
			var applied bool
			if customEntry.ThinkingBudget != nil {
				config = ThinkingConfig{Mode: ModeBudget, Budget: *customEntry.ThinkingBudget}
				applied = true
			} else if customEntry.ReasoningEffort != "" {
				config = ThinkingConfig{Mode: ModeLevel, Level: ThinkingLevel(customEntry.ReasoningEffort)}
				applied = true
			}
			if applied {
				log.WithFields(log.Fields{
					"model":    suffixResult.ModelName,
					"provider": toFormat,
					"mode":     config.Mode,
					"budget":   config.Budget,
					"level":    config.Level,
				}).Debug("thinking: fallback to custom config default values |")
				return config
			}
		}
	}

	if hasThinkingConfig(bodyConfig) {
		log.WithFields(log.Fields{
			"model":    suffixResult.ModelName,
			"provider": toFormat,
			"mode":     bodyConfig.Mode,
			"budget":   bodyConfig.Budget,
			"level":    bodyConfig.Level,
		}).Debug("thinking: original config from request |")
	}

	return bodyConfig
}
