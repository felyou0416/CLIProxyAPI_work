package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

type Transport struct {
	baseURL    *url.URL
	apiKey     string
	httpClient *http.Client
}

func NewTransport(config UpstreamConfig) (*Transport, error) {
	parsed, err := url.Parse(strings.TrimRight(strings.TrimSpace(config.BaseURL), "/"))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("invalid upstream.base_url")
	}
	connectTimeout := time.Duration(config.ConnectTimeoutSeconds) * time.Second
	if connectTimeout <= 0 {
		connectTimeout = 10 * time.Second
	}
	client := &http.Client{Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, DialContext: (&net.Dialer{Timeout: connectTimeout}).DialContext}}
	return &Transport{baseURL: parsed, apiKey: config.APIKey, httpClient: client}, nil
}

func (t *Transport) endpoint() string {
	base := strings.TrimRight(t.baseURL.String(), "/")
	if strings.HasSuffix(base, "/v1") {
		return base + "/chat/completions"
	}
	return base + "/v1/chat/completions"
}

func (t *Transport) Do(ctx context.Context, request ChatRequest, timeout time.Duration) (*http.Response, error) {
	return t.do(ctx, request, timeout)
}

func (t *Transport) do(ctx context.Context, request ChatRequest, timeout time.Duration) (*http.Response, error) {
	payload, err := json.Marshal(request)
	if err != nil {
		return nil, fmt.Errorf("encode upstream request: %w", err)
	}
	var cancel context.CancelFunc
	if timeout > 0 {
		ctx, cancel = context.WithTimeout(ctx, timeout)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, t.endpoint(), bytes.NewReader(payload))
	if err != nil {
		if cancel != nil {
			cancel()
		}
		return nil, fmt.Errorf("create upstream request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if t.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+t.apiKey)
	}
	resp, err := t.httpClient.Do(req)
	if err != nil {
		if cancel != nil {
			cancel()
		}
		return nil, fmt.Errorf("upstream request: %w", err)
	}
	if cancel != nil {
		resp.Body = &cancelReadCloser{ReadCloser: resp.Body, cancel: cancel}
	}
	return resp, nil
}

type cancelReadCloser struct {
	io.ReadCloser
	cancel context.CancelFunc
	once   sync.Once
}

func (r *cancelReadCloser) Close() error {
	err := r.ReadCloser.Close()
	if r.cancel != nil {
		r.once.Do(r.cancel)
	}
	return err
}

type bodyLimitError struct {
	limit int64
}

func (e bodyLimitError) Error() string {
	return fmt.Sprintf("body exceeds %d bytes", e.limit)
}

func readLimited(body io.Reader, limit int64) ([]byte, error) {
	if limit <= 0 {
		return nil, fmt.Errorf("body limit must be positive")
	}
	raw, err := io.ReadAll(io.LimitReader(body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, bodyLimitError{limit: limit}
	}
	return raw, nil
}
