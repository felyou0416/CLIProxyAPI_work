# PortBindingTools

Expose local-only TCP services through Windows portproxy.

Examples:

```powershell
# Show managed portproxy and firewall rules
powershell -ExecutionPolicy Bypass -File .\PortBindingTools\set-port-bindings.ps1 -Ports 8317,1900 -Status

# Expose TCP ports and add matching firewall rules for trusted VPN addresses only
powershell -ExecutionPolicy Bypass -File .\PortBindingTools\set-port-bindings.ps1 -Ports 8317,1900 -RemoteAddress fd7a:115c:a1e0::9e39:c580,100.89.197.128 -Firewall -Elevate

# Remove managed portproxy and firewall rules
powershell -ExecutionPolicy Bypass -File .\PortBindingTools\set-port-bindings.ps1 -Ports 8317 -Remove -Elevate
```

This tool manages TCP only. UDP ports such as SSDP `1900/UDP` cannot be exposed with Windows portproxy.
