package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
)

func main() {
	configPath := flag.String("config", "claude-adapter.yaml", "adapter YAML configuration")
	flag.Parse()
	config, err := LoadConfig(resolveConfigPath(*configPath))
	if err != nil {
		log.Fatal(err)
	}
	if !config.Enabled {
		log.Fatal("adapter is disabled in configuration")
	}
	transport, err := NewTransport(config.Upstream)
	if err != nil {
		log.Fatal(err)
	}
	server, err := NewServer(config, transport)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("claude adapter listening on %s", config.Address())
	if err := http.ListenAndServe(config.Address(), server.Handler()); err != nil {
		log.Fatal(fmt.Errorf("serve adapter: %w", err))
	}
}
