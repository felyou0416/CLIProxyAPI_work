package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

func TranslateRequest(req MessageRequest, route Route, config Config) (ChatRequest, error) {
	if strings.TrimSpace(req.Model) == "" {
		return ChatRequest{}, fieldError("model", "is required")
	}
	if req.MaxTokens <= 0 {
		return ChatRequest{}, fieldError("max_tokens", "must be positive")
	}
	if len(req.Messages) == 0 {
		return ChatRequest{}, fieldError("messages", "must contain at least one message")
	}
	if req.TopK != nil {
		return ChatRequest{}, fieldError("top_k", "is not supported by the OpenAI chat-completions bridge")
	}
	if hasJSONValue(req.Thinking) && strings.EqualFold(strings.TrimSpace(config.Thinking.Unsupported), "reject") {
		return ChatRequest{}, fieldError("thinking", "is not supported by this route")
	}
	if hasJSONValue(req.ToolChoice) && !config.Features.Tools {
		return ChatRequest{}, fieldError("tool_choice", "tools are disabled")
	}

	model := strings.TrimSpace(route.Alias)
	if model == "" {
		model = strings.TrimSpace(req.Model)
	}
	result := ChatRequest{
		Model:       model,
		MaxTokens:   req.MaxTokens,
		Temperature: req.Temperature,
		TopP:        req.TopP,
		Stop:        req.StopSequences,
		Stream:      req.Stream,
	}
	if len(req.Tools) > 0 {
		if !config.Features.Tools {
			return ChatRequest{}, fieldError("tools", "are disabled")
		}
		for i, tool := range req.Tools {
			if strings.TrimSpace(tool.Name) == "" {
				return ChatRequest{}, fieldError(fmt.Sprintf("tools[%d].name", i), "is required")
			}
			if len(bytes.TrimSpace(tool.InputSchema)) == 0 {
				return ChatRequest{}, fieldError(fmt.Sprintf("tools[%d].input_schema", i), "is required")
			}
			result.Tools = append(result.Tools, ChatTool{
				Type: "function",
				Function: ChatFunction{
					Name:        tool.Name,
					Description: tool.Description,
					Parameters:  append(json.RawMessage(nil), tool.InputSchema...),
				},
			})
		}
	}
	if hasJSONValue(req.ToolChoice) {
		choice, err := translateToolChoice(req.ToolChoice)
		if err != nil {
			return ChatRequest{}, fieldError("tool_choice", err.Error())
		}
		result.ToolChoice = choice
	}
	if hasJSONValue(req.System) {
		content, err := translateSystem(req.System)
		if err != nil {
			return ChatRequest{}, err
		}
		result.Messages = append(result.Messages, ChatMessage{Role: "system", Content: content})
	}
	for i, message := range req.Messages {
		translated, err := translateMessage(message, config, fmt.Sprintf("messages[%d]", i))
		if err != nil {
			return ChatRequest{}, err
		}
		result.Messages = append(result.Messages, translated...)
	}
	return result, nil
}

func translateSystem(raw json.RawMessage) (json.RawMessage, error) {
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return json.RawMessage(strconvQuote(text)), nil
	}
	blocks, err := decodeBlocks(raw)
	if err != nil {
		return nil, fieldError("system", "must be a string or content block array")
	}
	var parts []ChatContentPart
	for i, block := range blocks {
		if block.Type == "text" {
			parts = append(parts, ChatContentPart{Type: "text", Text: block.Text})
			continue
		}
		return nil, fieldError(fmt.Sprintf("system[%d]", i), "only text blocks are supported")
	}
	if len(parts) == 1 {
		return json.Marshal(parts[0].Text)
	}
	return json.Marshal(parts)
}

func translateMessage(message Message, config Config, path string) ([]ChatMessage, error) {
	role := strings.ToLower(strings.TrimSpace(message.Role))
	if role != "user" && role != "assistant" {
		return nil, fieldError(path+".role", "must be user or assistant")
	}
	if text, ok := rawString(message.Content); ok {
		return []ChatMessage{{Role: role, Content: json.RawMessage(strconvQuote(text))}}, nil
	}
	blocks, err := decodeBlocks(message.Content)
	if err != nil {
		return nil, fieldError(path+".content", "must be a string or content block array")
	}
	var parts []ChatContentPart
	var output []ChatMessage
	flush := func() {
		if len(parts) == 0 {
			return
		}
		content, _ := json.Marshal(parts)
		output = append(output, ChatMessage{Role: role, Content: content})
		parts = nil
	}
	for i, block := range blocks {
		blockPath := fmt.Sprintf("%s.content[%d]", path, i)
		switch block.Type {
		case "text":
			parts = append(parts, ChatContentPart{Type: "text", Text: block.Text})
		case "image":
			if !config.Features.Images {
				return nil, fieldError(blockPath, "images are disabled")
			}
			image, err := translateImage(block.Source)
			if err != nil {
				return nil, fieldError(blockPath+".source", err.Error())
			}
			parts = append(parts, ChatContentPart{Type: "image_url", ImageURL: &ChatImageURL{URL: image}})
		case "tool_use":
			if role != "assistant" {
				return nil, fieldError(blockPath, "tool_use is only valid in assistant messages")
			}
			flush()
			input := block.Input
			if len(bytes.TrimSpace(input)) == 0 {
				input = json.RawMessage("{}")
			}
			if !json.Valid(input) {
				return nil, fieldError(blockPath+".input", "must be valid JSON")
			}
			output = append(output, ChatMessage{Role: "assistant", ToolCalls: []ChatToolCall{{
				ID:       block.ID,
				Type:     "function",
				Function: ChatFunctionCall{Name: block.Name, Arguments: string(input)},
			}}})
		case "tool_result":
			if role != "user" {
				return nil, fieldError(blockPath, "tool_result is only valid in user messages")
			}
			flush()
			content, err := translateToolResultContent(block.Content, blockPath+".content")
			if err != nil {
				return nil, err
			}
			output = append(output, ChatMessage{Role: "tool", ToolCallID: block.ToolUseID, Content: content})
		case "thinking", "redacted_thinking":
			if strings.EqualFold(strings.TrimSpace(config.Thinking.Unsupported), "strip") {
				continue
			}
			return nil, fieldError(blockPath, "thinking blocks are not supported by this route")
		case "document":
			return nil, fieldError(blockPath, "document blocks are not supported by this route")
		default:
			return nil, fieldError(blockPath+".type", "unsupported content block type "+block.Type)
		}
	}
	flush()
	return output, nil
}

func translateImage(raw json.RawMessage) (string, error) {
	var source ImageSource
	if err := json.Unmarshal(raw, &source); err != nil {
		return "", fmt.Errorf("must be an image source object")
	}
	switch source.Type {
	case "url":
		if strings.TrimSpace(source.URL) == "" {
			return "", fmt.Errorf("url is required")
		}
		return source.URL, nil
	case "base64":
		if strings.TrimSpace(source.MediaType) == "" || strings.TrimSpace(source.Data) == "" {
			return "", fmt.Errorf("media_type and data are required for base64 images")
		}
		return "data:" + source.MediaType + ";base64," + source.Data, nil
	default:
		return "", fmt.Errorf("source.type %q is unsupported", source.Type)
	}
}

func translateToolResultContent(raw json.RawMessage, path string) (json.RawMessage, error) {
	if text, ok := rawString(raw); ok {
		return json.RawMessage(strconvQuote(text)), nil
	}
	blocks, err := decodeBlocks(raw)
	if err != nil {
		return nil, fieldError(path, "must be a string or content block array")
	}
	var parts []ChatContentPart
	for i, block := range blocks {
		switch block.Type {
		case "text":
			parts = append(parts, ChatContentPart{Type: "text", Text: block.Text})
		case "image":
			return nil, fieldError(fmt.Sprintf("%s[%d]", path, i), "images in tool results are not supported")
		default:
			return nil, fieldError(fmt.Sprintf("%s[%d].type", path, i), "unsupported tool result block")
		}
	}
	if len(parts) == 1 {
		return json.Marshal(parts[0].Text)
	}
	return json.Marshal(parts)
}

func translateToolChoice(raw json.RawMessage) (json.RawMessage, error) {
	var value string
	if json.Unmarshal(raw, &value) == nil {
		switch value {
		case "auto", "none", "required":
			return json.RawMessage(strconvQuote(value)), nil
		case "any":
			return json.RawMessage(`"required"`), nil
		default:
			return nil, fmt.Errorf("choice %q is unsupported", value)
		}
	}
	var named struct {
		Type string `json:"type"`
		Name string `json:"name"`
	}
	if err := json.Unmarshal(raw, &named); err != nil || named.Type != "tool" || strings.TrimSpace(named.Name) == "" {
		return nil, fmt.Errorf("must be auto, none, any, or a named tool")
	}
	return json.Marshal(map[string]any{"type": "function", "function": map[string]string{"name": named.Name}})
}

func decodeBlocks(raw json.RawMessage) ([]ContentBlock, error) {
	var blocks []ContentBlock
	if err := json.Unmarshal(raw, &blocks); err != nil {
		return nil, err
	}
	return blocks, nil
}

func rawString(raw json.RawMessage) (string, bool) {
	var value string
	if json.Unmarshal(raw, &value) != nil {
		return "", false
	}
	return value, true
}

func hasJSONValue(raw json.RawMessage) bool {
	return len(bytes.TrimSpace(raw)) > 0 && !bytes.Equal(bytes.TrimSpace(raw), []byte("null"))
}

func strconvQuote(value string) string {
	encoded, _ := json.Marshal(value)
	return string(encoded)
}

type fieldErrorValue struct{ Field, Message string }

func (e fieldErrorValue) Error() string      { return e.Field + " " + e.Message }
func fieldError(field, message string) error { return fieldErrorValue{Field: field, Message: message} }

func TranslateResponse(raw []byte, status int, requestID string) (MessageResponse, error) {
	var response ChatResponse
	if err := json.Unmarshal(raw, &response); err != nil {
		return MessageResponse{}, fmt.Errorf("decode upstream response: %w", err)
	}
	if response.Error != nil {
		return MessageResponse{}, upstreamAPIError(status, response.Error.Message, requestID)
	}
	if len(response.Choices) == 0 {
		return MessageResponse{}, fmt.Errorf("upstream response contains no choices")
	}
	choice := response.Choices[0]
	result := MessageResponse{
		ID:         response.ID,
		Type:       "message",
		Role:       "assistant",
		Model:      response.Model,
		StopReason: mapStopReason(choice.FinishReason, len(choice.Message.ToolCalls) > 0),
	}
	if result.ID == "" {
		result.ID = requestID
	}
	if result.Model == "" {
		result.Model = "unknown"
	}
	content, err := responseContent(choice.Message)
	if err != nil {
		return MessageResponse{}, err
	}
	result.Content = content
	if response.Usage != nil {
		result.Usage = Usage{InputTokens: response.Usage.PromptTokens, OutputTokens: response.Usage.CompletionTokens}
	}
	return result, nil
}

func responseContent(message ChatMessage) ([]ContentBlock, error) {
	var result []ContentBlock
	if text, ok := rawString(message.Content); ok && text != "" {
		result = append(result, ContentBlock{Type: "text", Text: text})
	} else if len(message.Content) > 0 && !bytes.Equal(bytes.TrimSpace(message.Content), []byte("null")) {
		var parts []ChatContentPart
		if err := json.Unmarshal(message.Content, &parts); err != nil {
			return nil, fmt.Errorf("decode upstream content: %w", err)
		}
		for _, part := range parts {
			if part.Type != "text" {
				return nil, fmt.Errorf("upstream content type %q is unsupported", part.Type)
			}
			result = append(result, ContentBlock{Type: "text", Text: part.Text})
		}
	}
	for _, call := range message.ToolCalls {
		input := json.RawMessage(call.Function.Arguments)
		if !json.Valid(input) {
			input = json.RawMessage("{}")
		}
		result = append(result, ContentBlock{Type: "tool_use", ID: call.ID, Name: call.Function.Name, Input: input})
	}
	return result, nil
}

func mapStopReason(reason string, hasTools bool) string {
	switch reason {
	case "tool_calls", "function_call":
		return "tool_use"
	case "length", "max_tokens":
		return "max_tokens"
	case "stop":
		return "end_turn"
	case "content_filter":
		return "refusal"
	case "":
		if hasTools {
			return "tool_use"
		}
		return "end_turn"
	default:
		return reason
	}
}
