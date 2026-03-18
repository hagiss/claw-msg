# claw-msg: Agent-to-Agent Messaging Layer

## Overview

AI 에이전트들이 머신 간에 서로 통신할 수 있는 메시징 레이어.
하나의 패키지로 **broker(서버)**와 **SDK(클라이언트)** 모두 제공하며, OpenClaw 플러그인으로 네이티브 통합 가능.

**PyPI**: `pip install claw-msg`
**GitHub**: `/home/jiho/workspace/claw-msg/`

---

## Architecture

```
머신 A                                    머신 B
┌─────────────────────┐                  ┌─────────────────────┐
│ OpenClaw Gateway     │                  │ OpenClaw Gateway     │
│  ├─ 카카오 에이전트   │                  │  ├─ 텔레그램 에이전트 │
│  ├─ SOUL.md, MEMORY  │                  │  ├─ SOUL.md, MEMORY  │
│  └─ claw-msg 플러그인 │                  │  └─ claw-msg 플러그인 │
│       ↕ WebSocket    │                  │       ↕ WebSocket    │
└───────┬─────────────┘                  └───────┬─────────────┘
        │                                         │
        └──────────► claw-msg broker ◄────────────┘
                     (중앙 메시지 중계)
```

- **Broker**: FastAPI 서버. 에이전트 등록, 메시지 라우팅, 오프라인 큐 관리
- **플러그인**: OpenClaw gateway에 채널로 등록. gateway 시작 시 자동으로 broker에 연결
- **에이전트 입장**: 카카오/텔레그램과 동일하게 메시지 수신 → context 로드 → LLM 응답 → 회신

---

## Components

### 1. claw-msg Broker (Python/FastAPI)

| 기능 | 설명 |
|---|---|
| 에이전트 등록/검색 | 이름, capability 기반 등록 및 검색 |
| WebSocket 실시간 전송 | auth handshake → message.send/receive → ack |
| HTTP polling fallback | WebSocket 없이 REST로도 메시지 송수신 |
| 룸 (그룹 메시지) | create/join/leave + 브로드캐스트 |
| 오프라인 큐 | 수신자 오프라인 시 7일 TTL 보관, 재접속 시 flush |
| Rate limiting | 에이전트당 분당 60 메시지 (token bucket) |
| Presence | online/offline/last_seen 자동 추적 |
| 30초 heartbeat | ping/pong으로 연결 유지 |

### 2. Python SDK

```python
from claw_msg import Agent

agent = Agent("http://broker:8000", name="my-agent")
await agent.register()
await agent.send("<agent-id>", "hello!")
```

5줄로 에이전트 간 통신 가능. WebSocket 자동 연결/재연결 지원.

### 3. CLI

```bash
claw-msg serve          # broker 실행
claw-msg register       # 에이전트 등록
claw-msg send           # 메시지 전송
claw-msg listen         # 메시지 수신 대기
claw-msg bridge         # OpenClaw ↔ broker 브릿지 (standalone)
claw-msg rooms          # 룸 관리
claw-msg daemon         # webhook 포워딩 데몬
claw-msg install-service # systemd/launchd 서비스 등록
```

### 4. OpenClaw 채널 플러그인

`extensions/claw-msg/`에 위치. OpenClaw gateway의 채널로 동작하여 별도 프로세스 없이 네이티브 통합.

---

## Database (SQLite + WAL)

| 테이블 | 역할 |
|---|---|
| agents | 등록 정보, bcrypt 토큰 해시, 상태 |
| messages | 전체 메시지 히스토리 |
| rooms | 룸 메타데이터 |
| room_members | 룸-에이전트 멤버십 |
| delivery_queue | 오프라인 메시지 큐 (7일 TTL) |

---

## WebSocket Protocol

JSON 프레임 기반. 주요 프레임:

| Frame | 방향 | 용도 |
|---|---|---|
| `auth` | client → server | Bearer token 인증 |
| `auth.ok` / `auth.fail` | server → client | 인증 결과 |
| `message.send` | client → server | 메시지 전송 |
| `message.receive` | server → client | 메시지 수신 |
| `message.ack` | 양방향 | at-least-once 전송 확인 |
| `ping` / `pong` | 양방향 | 30초 heartbeat |

---

## Security

- **토큰 인증**: 등록 시 `secrets.token_urlsafe(32)` 발급
- **이중 해시**: SHA-256 (O(1) lookup) + bcrypt (검증)
- **Bearer token**: 모든 HTTP/WebSocket 요청에 필요

---

## 사용법: 이 머신에서 설정

### Step 1 — Broker 실행

```bash
claw-msg serve --port 8000
```

### Step 2 — 에이전트 등록

```bash
claw-msg register --name "jiho-agent" --broker http://localhost:8000
# → agent_id: abc-123-...
# → token: xxxx...
```

### Step 3 — 플러그인 의존성 설치

```bash
cd ~/workspace/OpenClaw/extensions/claw-msg
pnpm install
```

### Step 4 — openclaw.json에 채널 추가

`channels` 섹션에:

```json
"claw-msg": {
  "enabled": true,
  "broker": "http://localhost:8000",
  "token": "<Step 2에서 받은 토큰>",
  "name": "jiho-agent",
  "dmPolicy": "open"
}
```

### Step 5 — 바인딩 추가

`bindings` 배열에 어떤 에이전트가 claw-msg 메시지를 받을지 지정:

```json
{
  "agentId": "<대상-openclaw-agent-id>",
  "match": { "channel": "claw-msg" }
}
```

### Step 6 — Gateway 재시작

```bash
openclaw gateway
```

Gateway 시작 시 자동으로 broker에 WebSocket 연결됨.

---

## 사용법: 다른 머신에서 설정

### Step 1 — claw-msg 설치

```bash
pip install claw-msg
```

### Step 2 — 에이전트 등록

```bash
claw-msg register --name "other-agent" --broker http://<broker-ip>:8000
```

### Step 3 — OpenClaw 플러그인 설치

`extensions/claw-msg/` 폴더를 복사하고:

```bash
cd extensions/claw-msg && pnpm install
```

### Step 4 — openclaw.json에 채널 추가

```json
"claw-msg": {
  "enabled": true,
  "broker": "http://<broker-ip>:8000",
  "token": "<Step 2에서 받은 토큰>",
  "name": "other-agent",
  "dmPolicy": "open"
}
```

### Step 5 — 바인딩 + Gateway 재시작

이 머신과 동일.

---

## 에이전트 간 대화 연결 방식

현재는 **관리자가 직접 연결을 설정**하는 구조:

1. 양쪽 머신에서 각각 `claw-msg register`로 agent_id/token 발급
2. 각 `openclaw.json`의 bindings에 상대방 UUID를 peer로 지정
3. 에이전트의 context 파일(INSTRUCTIONS.md 등)에 상대 에이전트 정보 기록

```markdown
## 연결된 에이전트
- 번역 에이전트: abc-123-... (claw-msg 채널로 연락 가능)
```

에이전트는 관리자가 연결해준 상대와만 대화. 자동 디스커버리는 의도적으로 미구현.

---

## 카카오톡 연동 시나리오

```
사용자 (카카오) → "이거 번역해줘"
    ↓
카카오 에이전트 (SOUL.md, MEMORY.md 기반 판단)
    → "번역은 다른 에이전트가 잘하지"
    ↓
claw-msg 채널로 번역 에이전트에게 요청
    ↓
다른 머신의 번역 에이전트 (자기 context 기반 응답)
    ↓
응답 수신 → 카카오톡으로 사용자에게 전달
```

---

## 프로젝트 구조

```
claw-msg/                              # PyPI 패키지 (pip install claw-msg)
├── src/claw_msg/
│   ├── common/                        # 공유 모델, 프로토콜, 에러
│   │   ├── models.py
│   │   ├── protocol.py
│   │   └── errors.py
│   ├── server/                        # Broker 서버
│   │   ├── app.py                     # FastAPI factory + lifespan
│   │   ├── config.py
│   │   ├── database.py                # aiosqlite + WAL
│   │   ├── auth.py                    # bcrypt token auth
│   │   ├── broker.py                  # WebSocket 메시지 라우팅
│   │   ├── presence.py                # online/offline 추적
│   │   ├── rate_limit.py              # 60 msg/min token bucket
│   │   ├── offline_queue.py           # 7일 TTL 오프라인 큐
│   │   ├── routes_agents.py           # 등록, 검색, 프로필
│   │   ├── routes_messages.py         # HTTP 메시지 송수신
│   │   ├── routes_rooms.py            # 룸 CRUD
│   │   └── routes_ws.py              # WebSocket endpoint
│   ├── client/                        # Python SDK
│   │   ├── agent.py                   # Agent 클래스 (메인 인터페이스)
│   │   ├── connection.py              # WebSocket + auto-reconnect
│   │   ├── credentials.py             # ~/.claw-msg/ 토큰 저장
│   │   └── http.py                    # HTTP fallback
│   ├── bridge.py                      # OpenClaw ↔ broker 브릿지 (standalone)
│   ├── daemon/                        # Webhook 포워딩 데몬
│   └── cli/                           # Click CLI
└── tests/                             # 21개 테스트 (전체 통과)

OpenClaw/extensions/claw-msg/          # OpenClaw 채널 플러그인
├── openclaw.plugin.json
├── package.json
├── index.ts
└── src/
    ├── channel.ts                     # ChannelPlugin 정의
    ├── monitor.ts                     # WebSocket으로 broker 연결 + 수신
    ├── inbound.ts                     # 수신 메시지 → agent 라우팅 + 응답
    ├── send.ts                        # 아웃바운드 메시지 전송
    ├── accounts.ts                    # 계정 해석
    ├── runtime.ts                     # PluginRuntime 싱글톤
    └── types.ts                       # 타입 정의
```

---

## 테스트

```bash
cd ~/workspace/claw-msg
pip install -e ".[dev]"
pytest tests/ -v
# 21 passed
```

| 테스트 파일 | 커버리지 |
|---|---|
| test_registration.py | 등록, 프로필, 검색, 인증 실패 |
| test_direct_messaging.py | 1:1 메시지, 히스토리, 유효성 |
| test_rooms.py | 룸 생성/참여/퇴장, 멤버 목록, 룸 메시지 |
| test_offline_queue.py | 오프라인 저장, flush, ack |
| test_websocket.py | WS 인증, ping/pong, WS 다이렉트 메시지 |
| test_sdk_agent.py | SDK 등록+전송, 룸 조작 |

---

## 의존성

```
fastapi, uvicorn[standard], aiosqlite, bcrypt, websockets, httpx, pydantic, click, python-dotenv
```

Python 3.11+ 필요. 별도 DB 서버 불필요 (SQLite).
