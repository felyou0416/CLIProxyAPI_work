package mediaproxy

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/api/handlers"
	"github.com/tidwall/gjson"
)

const defaultMediaProxyURL = "http://127.0.0.1:8320"

func IsMediaModel(modelName string) bool {
	model := strings.ToLower(strings.TrimSpace(modelName))
	return strings.Contains(model, "image") || strings.Contains(model, "video")
}

func ProxyOpenAIChat(c *gin.Context, rawJSON []byte) {
	target := mediaProxyURL() + "/v1/chat/completions"
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, target, bytes.NewReader(rawJSON))
	if err != nil {
		writeProxyError(c, http.StatusBadGateway, "media_proxy_error", "media proxy request init failed: "+err.Error())
		return
	}
	copyProxyHeaders(c, req)

	client := &http.Client{Timeout: 6 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		if startErr := ensureStarted(); startErr == nil {
			req, _ = http.NewRequestWithContext(c.Request.Context(), http.MethodPost, target, bytes.NewReader(rawJSON))
			copyProxyHeaders(c, req)
			resp, err = client.Do(req)
		}
		if err != nil {
			writeProxyError(c, http.StatusBadGateway, "media_proxy_unavailable", "media proxy unavailable: "+err.Error())
			return
		}
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		writeProxyError(c, http.StatusBadGateway, "media_proxy_error", "media proxy response read failed: "+err.Error())
		return
	}

	contentType := strings.TrimSpace(resp.Header.Get("Content-Type"))
	if contentType == "" {
		contentType = "application/json"
	}
	c.Data(resp.StatusCode, contentType, body)
}

func ClaudeMessagesToOpenAIChat(rawJSON []byte) []byte {
	var req map[string]any
	if err := json.Unmarshal(rawJSON, &req); err != nil {
		return rawJSON
	}
	out := map[string]any{
		"model":    gjson.GetBytes(rawJSON, "model").String(),
		"messages": req["messages"],
	}
	for _, key := range []string{"stream", "size", "n", "seconds", "aspect_ratio", "images", "image", "return_base64", "extra_body"} {
		if value, ok := req[key]; ok {
			out[key] = value
		}
	}
	data, err := json.Marshal(out)
	if err != nil {
		return rawJSON
	}
	return data
}

func mediaProxyURL() string {
	if value := strings.TrimSpace(os.Getenv("CLIPROXYAPI_MEDIA_PROXY_URL")); value != "" {
		return strings.TrimRight(value, "/")
	}
	return defaultMediaProxyURL
}

func copyProxyHeaders(c *gin.Context, req *http.Request) {
	req.Header.Set("Content-Type", "application/json")
	if auth := strings.TrimSpace(c.Request.Header.Get("Authorization")); auth != "" {
		req.Header.Set("Authorization", auth)
	}
}

func writeProxyError(c *gin.Context, status int, typ, message string) {
	c.JSON(status, handlers.ErrorResponse{Error: handlers.ErrorDetail{
		Message: message,
		Type:    typ,
	}})
}

func ensureStarted() error {
	if strings.EqualFold(strings.TrimSpace(os.Getenv("CLIPROXYAPI_MEDIA_PROXY_AUTOSTART")), "false") {
		return os.ErrPermission
	}
	if portReady(300 * time.Millisecond) {
		return nil
	}
	cmd, err := startCommand()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if portReady(500 * time.Millisecond) {
			return nil
		}
		time.Sleep(250 * time.Millisecond)
	}
	return os.ErrDeadlineExceeded
}

func startCommand() (*exec.Cmd, error) {
	if raw := strings.TrimSpace(os.Getenv("CLIPROXYAPI_MEDIA_PROXY_COMMAND")); raw != "" {
		return exec.Command(raw), nil
	}
	root := strings.TrimSpace(os.Getenv("CLIPROXYAPI_MEDIA_PROXY_ROOT"))
	if root == "" {
		root = findRoot()
	}
	if root == "" {
		return nil, os.ErrNotExist
	}
	config := filepath.Join(root, "config.json")
	if _, err := os.Stat(config); err != nil {
		config = filepath.Join(root, "config.example.json")
	}
	if exe := filepath.Join(root, "CLIProxyAPI-MediaProxy.exe"); fileExists(exe) {
		cmd := exec.Command(exe, "-config", config)
		cmd.Dir = root
		return cmd, nil
	}
	cmd := exec.Command("go", "run", ".", "-config", config)
	cmd.Dir = root
	return cmd, nil
}

func findRoot() string {
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	for _, candidate := range []string{
		filepath.Join(cwd, "CLIProxyAPI-MediaProxy"),
		filepath.Join(cwd, "..", "CLIProxyAPI-MediaProxy"),
		filepath.Join(cwd, "..", "..", "CLIProxyAPI-MediaProxy"),
	} {
		if fileExists(filepath.Join(candidate, "main.go")) {
			abs, _ := filepath.Abs(candidate)
			return abs
		}
	}
	return ""
}

func portReady(timeout time.Duration) bool {
	raw := strings.TrimPrefix(mediaProxyURL(), "http://")
	raw = strings.TrimPrefix(raw, "https://")
	if slash := strings.Index(raw, "/"); slash >= 0 {
		raw = raw[:slash]
	}
	if !strings.Contains(raw, ":") {
		raw += ":80"
	}
	conn, err := net.DialTimeout("tcp", raw, timeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
