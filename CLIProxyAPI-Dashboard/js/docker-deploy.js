/* Docker Deployment Reference */

function loadDockerDeploy() {
  const content = document.getElementById('docker-deploy-content');
  if (!content) return;
  content.innerHTML = `<div class="doc-section">
    <h3>Docker Compose (单节点)</h3>
    <pre class="doc-code">version: '3.8'
services:
  cliproxyapi:
    image: ghcr.io/router-for-me/cliproxyapi:latest
    ports:
      - "8317:8317"
    volumes:
      - ./storage:/app/storage
      - ./config.yaml:/app/config.yaml
    command: ["-config", "/app/config.yaml"]</pre>

    <h3>Docker Compose (集群模式 + Home 控制面)</h3>
    <pre class="doc-code">version: '3.8'
services:
  cliproxyapi:
    image: ghcr.io/router-for-me/cliproxyapi:latest
    ports:
      - "8317:8317"
    environment:
      HOME_JWT: \${HOME_JWT}
    volumes:
      - ./storage:/app/storage
    command: ["-config", "/app/config.yaml", "-home-jwt", "\${HOME_JWT}"]</pre>

    <h3>Dockerfile 参考</h3>
    <pre class="doc-code">FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY . .
RUN go build -o /cli-proxy-api ./cmd/server

FROM alpine:latest
COPY --from=builder /cli-proxy-api /usr/local/bin/
EXPOSE 8317
ENTRYPOINT ["cli-proxy-api", "-config", "/etc/cliproxyapi/config.yaml"]</pre>

    <h3>环境变量</h3>
    <table class="metric-table">
      <thead><tr><th>变量</th><th>作用</th></tr></thead>
      <tbody>
        <tr><td>HOME_JWT</td><td>Home 控制面 JWT</td></tr>
        <tr><td>PGSTORE_DSN</td><td>激活 Postgres 存储后端</td></tr>
        <tr><td>GITSTORE_GIT_URL</td><td>激活 Git 存储后端</td></tr>
        <tr><td>OBJECTSTORE_ENDPOINT</td><td>激活对象存储后端</td></tr>
        <tr><td>DEPLOY=cloud</td><td>云端部署模式</td></tr>
      </tbody>
    </table>
  </div>`;
}
