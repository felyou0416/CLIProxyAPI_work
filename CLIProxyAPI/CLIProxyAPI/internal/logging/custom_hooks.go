package logging

import (
	"net"
	"strings"

	"github.com/gin-gonic/gin"
)

var clientIPHeaderPriority = []string{
	"X-Forwarded-For",
	"CF-Connecting-IP",
	"True-Client-IP",
	"X-Real-IP",
	"X-Client-IP",
}

func normalizeClientIP(raw string) string {
	value := strings.TrimSpace(raw)
	if value == "" {
		return ""
	}
	value = strings.Trim(value, "\"[]")
	if strings.Contains(value, ":") {
		if host, _, err := net.SplitHostPort(value); err == nil {
			value = host
			value = strings.Trim(value, "[]")
		}
	}
	if zoneLess, _, ok := strings.Cut(value, "%"); ok {
		value = zoneLess
	}
	parsed := net.ParseIP(value)
	if parsed == nil {
		return ""
	}
	if ip4 := parsed.To4(); ip4 != nil {
		return ip4.String()
	}
	return parsed.String()
}

func firstForwardedClientIP(value string) string {
	for _, part := range strings.Split(value, ",") {
		if ip := normalizeClientIP(part); ip != "" {
			return ip
		}
	}
	return ""
}

// ProxyAwareClientIP extracts client IP using prioritized headers.
func ProxyAwareClientIP(c *gin.Context) string {
	if c == nil || c.Request == nil {
		return ""
	}
	for _, header := range clientIPHeaderPriority {
		value := c.GetHeader(header)
		if strings.TrimSpace(value) == "" {
			continue
		}
		if header == "X-Forwarded-For" {
			if ip := firstForwardedClientIP(value); ip != "" {
				return ip
			}
			continue
		}
		if ip := normalizeClientIP(value); ip != "" {
			return ip
		}
	}
	return normalizeClientIP(c.ClientIP())
}
