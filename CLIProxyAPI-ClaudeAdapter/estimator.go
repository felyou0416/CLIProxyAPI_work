package main

import (
	"encoding/json"
	"strings"
	"unicode/utf8"
)

const estimatorVersion = "approximate-v1"

func EstimateInputTokens(req MessageRequest) int {
	payload, err := json.Marshal(req)
	if err != nil {
		return 1
	}
	text := strings.TrimSpace(string(payload))
	if text == "" {
		return 1
	}
	// This intentionally estimates rather than pretending to be a provider tokenizer.
	count := (utf8.RuneCountInString(text) + 3) / 4
	if count < 1 {
		return 1
	}
	return count
}
