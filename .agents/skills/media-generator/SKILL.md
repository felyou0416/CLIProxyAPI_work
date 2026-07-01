---
name: media-generator
description: Generate images and videos locally using CLIProxyAPI endpoints.
---

# CLIProxyAPI Media Generator Skill

This skill documents how agents can call the local CLIProxyAPI server to draw images or generate videos, including model presets and prompting configurations.

## Model Presets & Parameters

### 1. Image Generation (POST `/v1/images/generations`)
- **URL**: `http://127.0.0.1:8317/v1/images/generations`
- **Default Model**: `agnes-agnes-image-2.0-flash`
- **Supported Models**:
  - `agnes-agnes-image-2.0-flash` (Fast image generation by Agnes)
  - `agnes-agnes-image-2.1-flash` (High quality image generation by Agnes)
  - `glm-CogView-3-Flash` (CogView drawing model by Zhipu)
- **Supported Resolutions (`size`)**:
  - `1024x1024` (Square, Default)
  - `720x1280` (Portrait)
  - `1280x720` (Landscape)
- **Headers**:
  - `Content-Type: application/json`
  - `Authorization: Bearer cliproxyapi`
- **Body Example**:
  ```json
  {
    "model": "agnes-agnes-image-2.0-flash",
    "prompt": "a beautiful forest",
    "size": "1024x1024"
  }
  ```

### 2. Video Generation (POST `/v1/videos/generations`)
- **URL**: `http://127.0.0.1:8317/v1/videos/generations`
- **Default Model**: `agnes-agnes-video-v2.0`
- **Supported Models**:
  - `agnes-agnes-video-v2.0` (Agnes custom video)
  - `sora-2` (Grok / Sora Video model)
- **Supported Resolutions (`size`)**:
  - `1280x704` (Landscape, Default)
  - `720x1280` (Portrait)
- **Headers**:
  - `Content-Type: application/json`
  - `Authorization: Bearer cliproxyapi`
- **Body Example**:
  ```json
  {
    "model": "agnes-agnes-video-v2.0",
    "prompt": "a beautiful forest, camera panning right",
    "size": "1280x704"
  }
  ```

### 3. Video Task Retrieval (GET `/v1/videos/:request_id`)
- **URL**: `http://127.0.0.1:8317/v1/videos/:request_id`
- **Headers**:
  - `Authorization: Bearer cliproxyapi`
