package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

type SSEConverter struct {
	writer         http.ResponseWriter
	flusher        http.Flusher
	requestID      string
	model          string
	started        bool
	closed         bool
	nextBlockIndex int
	textBlockIndex int
	textOpen       bool
	toolBlocks     map[int]*streamToolBlock
	toolOrder      []int
	stopReason     string
	outputSeen     int
	secrets        []string
}

type streamToolBlock struct {
	id        string
	name      string
	arguments strings.Builder
}

func NewSSEConverter(writer http.ResponseWriter, flusher http.Flusher, requestID, model string, secrets ...string) *SSEConverter {
	return &SSEConverter{
		writer:         writer,
		flusher:        flusher,
		requestID:      requestID,
		model:          model,
		textBlockIndex: -1,
		toolBlocks:     map[int]*streamToolBlock{},
		secrets:        secrets,
	}
}

func (c *SSEConverter) HandleData(data string) error {
	if data == "" || data == "[DONE]" {
		return nil
	}
	if c.closed {
		return fmt.Errorf("received upstream SSE event after stream was closed")
	}
	var response ChatResponse
	if err := json.Unmarshal([]byte(data), &response); err != nil {
		return fmt.Errorf("decode upstream SSE event: %w", err)
	}
	if response.Error != nil {
		return upstreamAPIError(http.StatusBadGateway, response.Error.Message, c.requestID)
	}
	if !c.started {
		if response.ID != "" {
			c.requestID = response.ID
		}
		if response.Model != "" {
			c.model = response.Model
		}
		c.emitMessageStart(response)
		c.started = true
	}
	for _, choice := range response.Choices {
		if len(choice.Delta.ToolCalls) > 0 {
			for _, call := range choice.Delta.ToolCalls {
				if err := c.handleToolDelta(call); err != nil {
					return err
				}
			}
		}
		if text, ok := rawString(choice.Delta.Content); ok && text != "" {
			c.ensureTextBlock()
			c.emit("content_block_delta", map[string]any{"type": "content_block_delta", "index": c.textBlockIndex, "delta": map[string]any{"type": "text_delta", "text": text}})
			c.outputSeen += len([]rune(text))
		}
		if choice.FinishReason != "" {
			c.stopReason = mapStopReason(choice.FinishReason, len(choice.Delta.ToolCalls) > 0)
		}
		if response.Usage != nil {
			c.outputSeen = response.Usage.CompletionTokens
		}
	}
	return nil
}

func (c *SSEConverter) handleToolDelta(call ChatToolCallDelta) error {
	if call.Index < 0 {
		return fmt.Errorf("upstream tool call index is negative")
	}
	block, exists := c.toolBlocks[call.Index]
	if !exists {
		block = &streamToolBlock{}
		c.toolBlocks[call.Index] = block
		c.toolOrder = append(c.toolOrder, call.Index)
	}
	if call.ID != "" {
		block.id = call.ID
	}
	if call.Function.Name != "" {
		block.name = call.Function.Name
	}
	block.arguments.WriteString(call.Function.Arguments)
	return nil
}

func (c *SSEConverter) ensureTextBlock() {
	if c.textOpen {
		return
	}
	c.textBlockIndex = c.nextBlockIndex
	c.nextBlockIndex++
	c.textOpen = true
	c.emit("content_block_start", map[string]any{"type": "content_block_start", "index": c.textBlockIndex, "content_block": map[string]any{"type": "text", "text": ""}})
}

func (c *SSEConverter) closeTextBlock() {
	if !c.textOpen {
		return
	}
	c.emit("content_block_stop", map[string]any{"type": "content_block_stop", "index": c.textBlockIndex})
	c.textOpen = false
}

func (c *SSEConverter) emitToolBlocks() {
	for _, openAIIndex := range c.toolOrder {
		block := c.toolBlocks[openAIIndex]
		index := c.nextBlockIndex
		c.nextBlockIndex++
		c.emit("content_block_start", map[string]any{"type": "content_block_start", "index": index, "content_block": map[string]any{"type": "tool_use", "id": block.id, "name": block.name, "input": map[string]any{}}})
		if arguments := block.arguments.String(); arguments != "" {
			c.emit("content_block_delta", map[string]any{"type": "content_block_delta", "index": index, "delta": map[string]any{"type": "input_json_delta", "partial_json": arguments}})
		}
		c.emit("content_block_stop", map[string]any{"type": "content_block_stop", "index": index})
	}
}

func (c *SSEConverter) emitMessageStart(response ChatResponse) {
	id := response.ID
	if id == "" {
		id = c.requestID
	}
	model := response.Model
	if model == "" {
		model = c.model
	}
	inputTokens := 0
	if response.Usage != nil {
		inputTokens = response.Usage.PromptTokens
	}
	c.emit("message_start", map[string]any{"type": "message_start", "message": map[string]any{
		"id": id, "type": "message", "role": "assistant", "model": model, "content": []any{}, "stop_reason": nil, "stop_sequence": nil, "usage": map[string]int{"input_tokens": inputTokens, "output_tokens": 0},
	}})
}

func (c *SSEConverter) Close() {
	if c.closed {
		return
	}
	if !c.started {
		c.emitMessageStart(ChatResponse{ID: c.requestID, Model: c.model})
		c.started = true
	}
	c.closeTextBlock()
	c.emitToolBlocks()
	if c.stopReason == "" {
		if len(c.toolBlocks) > 0 {
			c.stopReason = "tool_use"
		} else {
			c.stopReason = "end_turn"
		}
	}
	c.emit("message_delta", map[string]any{"type": "message_delta", "delta": map[string]any{"stop_reason": c.stopReason, "stop_sequence": nil}, "usage": map[string]int{"output_tokens": c.outputSeen}})
	c.emit("message_stop", map[string]any{"type": "message_stop"})
	c.closed = true
}

func (c *SSEConverter) EmitError(err error) {
	if err == nil || c.closed {
		return
	}
	message := err.Error()
	typeName := "api_error"
	if value, ok := err.(upstreamAPIErrorValue); ok {
		message = value.Message
		typeName = claudeErrorType(value.StatusCode)
	}
	message = redactSecrets(strings.TrimSpace(message), c.secrets...)
	if len(message) > 2048 {
		message = message[:2048]
	}
	c.emit("error", map[string]any{"type": "error", "error": map[string]string{"type": typeName, "message": message}})
	c.closed = true
}

func (c *SSEConverter) emit(event string, payload any) {
	data, _ := json.Marshal(payload)
	_, _ = fmt.Fprintf(c.writer, "event: %s\ndata: %s\n\n", event, data)
	c.flusher.Flush()
}

func normalizeSSEData(data string) string {
	return strings.TrimSpace(strings.TrimPrefix(data, "data:"))
}
