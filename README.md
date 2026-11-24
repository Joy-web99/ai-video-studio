# 🎬 AI Video Production Studio

A production-grade AI Video Studio that generates real MP4 videos. 
Built with FastAPI, FFmpeg, and a modern dark-cinema UI.

## ✨ Core Features
- **Smart Intent Guard:** Greetings like "Hi" won't trigger a video render.
- **Real MP4 Output:** Strictly verifies files with FFprobe. No fake images in the output box.
- **Cinematic Fallback:** If premium video APIs (Runway/Luma) are missing, it automatically uses AI images + FFmpeg Ken Burns motion to create a real video.
- **Multi-Agent System:** 5 specialized agents (Director, Image, Video, Audio, Editing) with Primary/Secondary/Backup API slots.
- **Live Workflow Logs:** Real-time Server-Sent Events (SSE) to show what the AI is doing.
- **Bangla Voice & Subtitle:** Built-in support for Bengali TTS and subtitles.

## 🚀 Deploy on Render
1. Push this repo to GitHub.
2. Go to Render.com -> New Web Service.
3. Connect your repo.
4. Render will automatically detect the `Dockerfile` and deploy.
5. Add your API keys in the dashboard UI.

## 🛠️ Tech Stack
- **Backend:** FastAPI, Python 3.11
- **Media Engine:** FFmpeg, FFprobe
- **AI Connectors:** Google Gemini, OpenAI, OpenRouter, Runway, ElevenLabs
- **Frontend:** Vanilla HTML/CSS/JS (No build step required)
