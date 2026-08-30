package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strings"
)

type upstreamAPIErrorValue struct {
	StatusCode int
	RequestID  string
	Message    string
}

func (e upstreamAPIErrorValue) Error() string { return e.Message }

func upstreamAPIError(status int, message, requestID string) error {
	return upstreamAPIErrorValue{StatusCode: status, RequestID: requestID, Message: message}
}

func writeClaudeError(w http.ResponseWriter, status int, requestID string, err error, secrets ...string) {
	if status < 400 || status > 599 {
		status = http.StatusInternalServerError
	}
	message := "internal adapter error"
	errorType := claudeErrorType(status)
	if value, ok := err.(upstreamAPIErrorValue); ok {
		if value.StatusCode >= 400 {
			status = value.StatusCode
		}
		if value.RequestID != "" {
			requestID = value.RequestID
		}
		message = value.Message
		errorType = claudeErrorType(status)
	} else if err != nil {
		message = err.Error()
	}
	message = redactSecrets(strings.TrimSpace(message), secrets...)
	if len(message) > 2048 {
		message = message[:2048]
	}
	payload := ClaudeErrorResponse{
		Type:      "error",
		Error:     ClaudeError{Type: errorType, Message: message},
		RequestID: requestID,
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("x-request-id", requestID)
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func claudeErrorType(status int) string {
	switch status {
	case http.StatusBadRequest:
		return "invalid_request_error"
	case http.StatusUnauthorized:
		return "authentication_error"
	case http.StatusForbidden:
		return "permission_error"
	case http.StatusNotFound:
		return "not_found_error"
	case http.StatusRequestTimeout, http.StatusGatewayTimeout:
		return "timeout_error"
	case http.StatusTooManyRequests:
		return "rate_limit_error"
	default:
		return "api_error"
	}
}

var secretPattern = regexp.MustCompile(`(?i)(sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,})`)

func redactSecrets(message string, secrets ...string) string {
	for _, secret := range secrets {
		if strings.TrimSpace(secret) != "" {
			message = strings.ReplaceAll(message, secret, "[redacted]")
		}
	}
	return secretPattern.ReplaceAllString(message, "[redacted]")
}

func fieldErrorMessage(err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("invalid request: %s", err.Error())
}
