package main

import (
	"encoding/json"
)

const estimatorVersion = "approximate-v2"

// EstimateInputTokens calculates a realistic token count for a Claude MessageRequest.
// It accounts for:
// - Conversation priming and message role framing tokens
// - System prompt (plain string or content blocks)
// - Messages (plain text or structured content blocks including tool_use, tool_result, images)
// - Tool definitions (name, description, parameter schemas, and framing overhead)
// - Distinct ratios for ASCII (code/English ~3.5-4 chars/token) vs CJK/emojis (~1.2-1.5 tokens/char)
func EstimateInputTokens(req MessageRequest) int {
	total := 3 // Base conversation priming tokens

	// 1. System Prompt
	if len(req.System) > 0 {
		if text, ok := rawString(req.System); ok {
			total += estimateText(text) + 2
		} else {
			var blocks []ContentBlock
			if err := json.Unmarshal(req.System, &blocks); err == nil {
				for _, b := range blocks {
					total += estimateText(b.Text)
				}
				total += len(blocks)
			} else {
				total += estimateText(string(req.System))
			}
		}
	}

	// 2. Messages
	for _, msg := range req.Messages {
		total += 3 // Role framing overhead per message (<|im_start|>role\n ... <|im_end|>)
		if text, ok := rawString(msg.Content); ok {
			total += estimateText(text)
			continue
		}
		var blocks []ContentBlock
		if err := json.Unmarshal(msg.Content, &blocks); err == nil && len(blocks) > 0 {
			for _, b := range blocks {
				switch b.Type {
				case "text":
					total += estimateText(b.Text)
				case "tool_use":
					total += 8 + estimateText(b.Name) + estimateText(string(b.Input))
				case "tool_result":
					if resText, ok := rawString(b.Content); ok {
						total += 4 + estimateText(resText)
					} else {
						total += 4 + estimateText(string(b.Content))
					}
				case "image":
					total += 1600 // Standard Claude high-res image token budget
				default:
					total += estimateText(b.Text) + estimateText(string(b.Content))
				}
			}
		} else {
			total += estimateText(string(msg.Content))
		}
	}

	// 3. Tools Definitions
	if len(req.Tools) > 0 {
		for _, tool := range req.Tools {
			total += 12 // Per-tool OpenAPI schema framing overhead
			total += estimateText(tool.Name)
			total += estimateText(tool.Description)
			total += estimateText(string(tool.InputSchema))
		}
	}

	// 4. Sanity Fallback
	if total < 1 {
		total = 1
	}
	return total
}

// estimateText estimates tokens for a UTF-8 string.
// ASCII (Latin letters, digits, whitespace, symbols): ~3.8 chars per token.
// CJK (Chinese, Japanese Kanji, Korean Hangul): ~1.3 tokens per rune.
// Other Unicode / Emojis: ~1.5 - 2 tokens per rune.
func estimateText(s string) int {
	if s == "" {
		return 0
	}
	asciiChars := 0
	cjkRunes := 0
	otherRunes := 0

	for _, r := range s {
		switch {
		case r <= 127:
			asciiChars++
		case (r >= 0x4E00 && r <= 0x9FFF) || // CJK Unified Ideographs
			(r >= 0x3400 && r <= 0x4DBF) || // CJK Unified Ideographs Extension A
			(r >= 0x20000 && r <= 0x2A6DF) || // CJK Extension B
			(r >= 0x3000 && r <= 0x303F) || // CJK Symbols and Punctuation
			(r >= 0xFF00 && r <= 0xFFEF) || // Halfwidth and Fullwidth Forms
			(r >= 0x3040 && r <= 0x309F) || // Hiragana
			(r >= 0x30A0 && r <= 0x30FF) || // Katakana
			(r >= 0xAC00 && r <= 0xD7AF): // Hangul Syllables
			cjkRunes++
		default:
			otherRunes++
		}
	}

	tokens := 0
	if asciiChars > 0 {
		tokens += (asciiChars + 3) / 4
	}
	if cjkRunes > 0 {
		// ~1.3 tokens per CJK character
		tokens += (cjkRunes*4 + 2) / 3
	}
	if otherRunes > 0 {
		tokens += otherRunes * 2
	}
	return tokens
}
