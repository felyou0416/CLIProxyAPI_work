# CLIProxyAPI Media Proxy

Standalone media-model proxy for image and video generation providers.

This program is intentionally separate from `CLIProxyAPI/CLIProxyAPI`, so media
model routing does not get mixed into the text-model proxy core.

## Build and Run

```powershell
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI-MediaProxy
.\build.ps1
.\cli-media-proxy.exe -config config.example.json
```

## Model Routing

Each model explicitly declares:

- `type`: `image` or `video`
- `endpoint`: upstream creation endpoint appended to `provider.base_url`
- `retrieve_endpoint`: optional polling endpoint for video tasks, using `{id}`
- `request_format`: `agnes-image`, `agnes-video`, `openai-image`, `openai-video`, or `passthrough`
- `response_format`: currently `auto`

The proxy uses the matched model's provider `base_url`, `api_key`, and headers.
This keeps OpenAI-style media, xAI-style media, Agnes-style media, and other
providers as provider-specific configuration instead of hard-coded handler names.

When `auth_dir` is configured, the proxy also reads existing auth JSON files from
`CLIProxyAPI/storage/auth`. For Agnes API-key entries it uses:

- `content.api_key`
- `content.base_url`
- `content.models`
- `content.provider`

That means the example config can keep `api_key` empty and reuse the stored auth.

## Adding Another Video Provider

For providers stored in `auth_dir`, add an `auth_providers` rule instead of
editing Go code:

```json
{
  "provider": "acme",
  "model_rules": [
    {
      "match_contains": "video",
      "type": "video",
      "endpoint": "/jobs",
      "retrieve_endpoint": "{base_url}/jobs/{id}",
      "method": "POST",
      "request_format": "passthrough",
      "poll_interval_ms": 2000,
      "poll_timeout_seconds": 180
    }
  ]
}
```

Available endpoint placeholders:

- `{base_url}`: the auth file's full `content.base_url`
- `{origin}`: scheme and host from `content.base_url`
- `{id}`, `{request_id}`, `{video_id}`: video task id during retrieval
- `{model}`: upstream model name

## Supported Entrypoints

- `POST /v1/chat/completions`
- `POST /v1/images/generations`
- `POST /v1/videos`
- `POST /v1/videos/generations`
- `GET /v1/videos/{id}`

For `chat/completions`, the proxy extracts the last user prompt, calls the
matched media model, and returns a normal chat completion containing Markdown:

- image: `![image](...)`
- video: `[video](...)`

## Agnes Image Format

`agnes-image` follows Agnes' image API shape:

- sends `model`, `prompt`, and `size`
- moves top-level `response_format` into `extra_body.response_format`
- moves top-level `image` into `extra_body.image`
- drops `tags`, because Agnes image-to-image does not need `tags: ["img2img"]`

## Agnes Video Format

`agnes-video` follows Agnes Video V2.0:

- creates tasks with `POST /v1/videos`
- supports single image-to-video with top-level `image`
- moves top-level `images` into `extra_body.image` for multi-image/keyframe flows
- retrieves results with `GET /agnesapi?video_id={video_id}`
- reads the completed video URL from `remixed_from_video_id`
