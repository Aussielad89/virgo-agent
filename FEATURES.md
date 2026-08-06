# Features — Virgo Desktop

## Core

| Page | Description |
|------|-------------|
| **Pipeline** | Run the 4-phase Write-Test-Fix loop with an animated DAG, live metrics, and split-view log. |
| **Chat** | Stream messages to/from a local LLM with slash commands, persona switching, branching, and voice mode. |
| **Dashboard** | Command-center overview of pipeline, swarm, and system health in one glance. |
| **Event Bus** | Inspect and filter the internal event stream in real time. |

## Agents

| Page | Description |
|------|-------------|
| **Mascot Chat** | Lightweight chat UI focused on persona-driven conversation. |
| **Activity Feed** | Chronological log of agent actions, file changes, and pipeline events. |
| **Leaderboard** | Ranked view of model performance across benchmark runs. |
| **Sessions** | Browse, replay, and export saved pipeline/swarm sessions. |
| **Swarm** | Launch and monitor multi-agent parallel runs. |
| **Bench** | Benchmark Ollama models on a standard prompt (latency + token table). |
| **Run Timeline** | Replay pipeline runs step-by-step with SVG timeline and phase jump. |
| **Artifacts** | Inspect files produced by pipeline runs (code, reports, logs). |
| **Memory** | View and search the persistent experience-memory store. |
| **Budget** | Track token/cost estimates across runs and models. |
| **Knowledge Base** | Manage the RAG index used for context injection in Chat. |

## System

| Page | Description |
|------|-------------|
| **Files** | Tree browser + Git panel (status, commit, push). |
| **Network** | Subnet scanner, device list, and port-check results. |
| **Diagnostics** | System health, log analysis, and remediation suggestions. |
| **Alerts** | Evaluates diagnostics/network reports and surfaces triggered alerts. |
| **Notifications** | Toast + tray notification history for pipeline and swarm completion. |
| **Logs** | Level filter + regex search + tail-follow across Virgo log files. |
| **Plugins** | List installed plugins, view metadata, and hot-reload. |
| **Procs** | Live process table for Python and Ollama with kill/restart buttons. |

## Extras

| Page | Description |
|------|-------------|
| **Scaffolds** | Generate project skeletons (FastAPI, CLI, Flask, lib, agent-tool). |
| **Models** | View pulled Ollama models, health status, and capability tags. |
| **Automation** | Desktop automation controls (macro recorder, scheduled runs). |
| **Sync** | Push/pull prompts and configs to a remote store. |
| **Fonts** | UI font family + size picker with live preview. |
| **Web Dashboard** | Embedded `virgo serve` dashboard (requires PyQt6-WebEngine). |
| **Recon Graph** | Visualize network topology and device relationships. |
| **C2 Commander** | Command-and-control terminal for remote agent sessions. |
| **Adversarial Arena** | Head-to-head model comparison with automated judging. |
| **Settings** | Theme, mode, custom CSS, .env editor, font controls, and UI preferences. |
| **About** | Version, credits, and dependency summary. |

## Experimental

| Page | Description |
|------|-------------|
| **Pipeline Sonification** | Hear pipeline phases as musical tones; optional `--watch` auto-play. |
| **Agent Dreams** | Idle-agent dream journal that replays memories and consolidates insights. |
| **Codebase Flavor** | Profile the repo’s style DNA (functional, OOP, async, etc.). |
| **Ghost Mode** | Speculative edits staged in `.virgo_ghost/` — manifest or discard later. |
| **Archaeology** | Git-history explorer — blame, timelines, and bisect introductions. |
| **Agent Empathy** | Read repo mood from commits and calibrate agent tone. |
| **Audit Chain** | Immutable hash chain of pipeline runs for tamper-evident logging. |
| **Pipeline Memes** | ASCII-art memes generated from pipeline outcomes. |
| **Stigmergic Heatmap** | Pheromone-trail heatmap across files showing hot spots and danger zones. |
| **Pipeline Divergence** | Git-like branching for agent runs — fork timelines and compare diffs. |
