package logging

import (
	"bytes"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	log "github.com/sirupsen/logrus"
)

func TestGinLogrusRecoveryRepanicsErrAbortHandler(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	engine.Use(GinLogrusRecovery())
	engine.GET("/abort", func(c *gin.Context) {
		panic(http.ErrAbortHandler)
	})

	req := httptest.NewRequest(http.MethodGet, "/abort", nil)
	recorder := httptest.NewRecorder()

	defer func() {
		recovered := recover()
		if recovered == nil {
			t.Fatalf("expected panic, got nil")
		}
		err, ok := recovered.(error)
		if !ok {
			t.Fatalf("expected error panic, got %T", recovered)
		}
		if !errors.Is(err, http.ErrAbortHandler) {
			t.Fatalf("expected ErrAbortHandler, got %v", err)
		}
		if err != http.ErrAbortHandler {
			t.Fatalf("expected exact ErrAbortHandler sentinel, got %v", err)
		}
	}()

	engine.ServeHTTP(recorder, req)
}

func TestGinLogrusRecoveryHandlesRegularPanic(t *testing.T) {
	gin.SetMode(gin.TestMode)

	engine := gin.New()
	engine.Use(GinLogrusRecovery())
	engine.GET("/panic", func(c *gin.Context) {
		panic("boom")
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	recorder := httptest.NewRecorder()

	engine.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", recorder.Code)
	}
}

func TestGinLogrusLoggerPrefersProxyHeaders(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var buf bytes.Buffer
	previousOut := log.StandardLogger().Out
	previousFormatter := log.StandardLogger().Formatter
	previousLevel := log.StandardLogger().Level
	log.SetOutput(&buf)
	log.SetFormatter(&log.TextFormatter{DisableTimestamp: true, DisableColors: true})
	log.SetLevel(log.InfoLevel)
	defer func() {
		log.SetOutput(previousOut)
		log.SetFormatter(previousFormatter)
		log.SetLevel(previousLevel)
	}()

	engine := gin.New()
	engine.Use(GinLogrusLogger())
	engine.GET("/v1/models", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	req.RemoteAddr = "127.0.0.1:45678"
	req.Header.Set("X-Forwarded-For", "203.0.113.7, 127.0.0.1")
	recorder := httptest.NewRecorder()

	engine.ServeHTTP(recorder, req)
	if !strings.Contains(buf.String(), "203.0.113.7") {
		t.Fatalf("expected log to contain forwarded client IP, got %q", buf.String())
	}
}

func TestProxyAwareClientIPNormalizesIPv6MappedAddress(t *testing.T) {
	gin.SetMode(gin.TestMode)

	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	req.RemoteAddr = "127.0.0.1:45678"
	req.Header.Set("X-Real-IP", "::ffff:155.254.108.7")
	c.Request = req

	if got := proxyAwareClientIP(c); got != "155.254.108.7" {
		t.Fatalf("proxyAwareClientIP = %q, want 155.254.108.7", got)
	}
}
