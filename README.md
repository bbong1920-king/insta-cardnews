# 해외 화제 뉴스 카드뉴스 자동화

외신에서 이미 화제가 된 뉴스를 골라 한국어 카드 1장과 상세 설명글을 만들고,
텔레그램으로 승인받은 뒤 인스타그램과 스레드에 자동으로 게시합니다.

```
[GitHub Actions, 하루 2번: 오전 6시 30분, 오후 4시 30분 (지금은 예약을 꺼 둠, 수동 실행만 가능)]
 외신 RSS 7곳 (+ Reddit) 수집
   → Claude: 여러 매체가 동시에 다루는 화제 뉴스 1건 선정
   → 해당 기사 원문 2~4개 읽고 한국어 카드 문구와 설명글 작성 (번역이 아니라 사실 요약)
   → 대표 이미지: Wikimedia Commons 무료 사진 중 Claude 가 보고 선택 → 없으면 AI 생성
   → 1080x1350 카드 이미지 렌더링
   → 텔레그램으로 미리보기 + [✅ 게시] [❌ 버리기] 버튼
   → 40분 동안 버튼 응답을 기다림 → 누르면 바로 인스타그램과 스레드에 게시 → 결과 링크를 텔레그램으로 알림
[GitHub Actions, 10분마다로 예약하지만 실제로는 몇 시간 간격]
   → 대기 시간이 지난 뒤 누른 버튼을 처리
```

## 저작권 원칙 (코드에 반영되어 있음)

- 기사 사진은 쓰지 않습니다. 자유 라이선스 사진만 쓰고, 카드에 **자료사진**과 작가/라이선스를 표기합니다.
  AI 이미지에는 **AI 생성 이미지**라고 표기합니다.
- 기사를 번역하지 않고, 여러 기사에서 확인된 사실을 새 문장으로 정리합니다. 설명글에 출처 매체를 표기합니다.
- 사망, 재난, 전쟁 같은 민감한 뉴스는 완전 자동 모드에서도 승인을 받도록 되어 있습니다.

---

## 설정 순서 (처음 한 번, 30분~1시간)

### 1. GitHub 저장소 만들기
1. GitHub 에서 **Public** 저장소를 새로 만들고 이 폴더 전체를 올립니다.
   - 인스타그램 API 는 이미지를 공개 URL 에서 가져가야 해서 공개 저장소의 raw 주소를 씁니다.
   - API 키는 Secrets 에만 들어가므로 코드가 공개돼도 안전합니다.
   - 비공개 저장소를 쓰려면 `config.yaml` 의 `public_base_url` 에 별도 이미지 호스팅 주소를 넣어야 합니다.
2. 저장소 **Settings → Actions → General → Workflow permissions** 를 *Read and write* 로 바꿉니다.

### 2. Claude 구독 토큰 (추가 비용 없음)
Claude Pro/Max 구독으로 돌리기 때문에 API 요금이 들지 않습니다.
1. PC 터미널에서 `claude setup-token` 을 실행합니다. (Claude Code 가 없다면 `npm install -g @anthropic-ai/claude-code`)
2. 브라우저에서 구독 계정으로 로그인하면 긴 토큰이 출력됩니다. 이것이 `CLAUDE_CODE_OAUTH_TOKEN` 입니다.
   - 토큰은 비밀번호처럼 다루세요. 유출되면 내 구독 사용량을 남이 쓸 수 있습니다.

> API 키로 돌리고 싶으면 `config.yaml` 의 `llm` 을 `api` 로 바꾸고 `ANTHROPIC_API_KEY` 를 등록하면 됩니다.

### 3. 텔레그램 승인 봇
1. 텔레그램에서 `@BotFather` 에게 `/newbot` 을 보내 봇을 만들고 토큰을 받습니다. 이것이 `TELEGRAM_BOT_TOKEN` 입니다.
2. 만든 봇에게 아무 메시지나 보냅니다.
3. PC 에서 `.env` 에 토큰을 넣고 `python -m cardnews chat-id` 를 실행하면 `TELEGRAM_CHAT_ID` 가 나옵니다.

### 4. 인스타그램 API
1. 인스타그램 계정을 **비즈니스** 또는 **크리에이터** 계정으로 전환합니다 (앱 설정 → 계정 유형).
2. [developers.facebook.com](https://developers.facebook.com) 에서 앱을 만들고, 사용 사례로
   **"Instagram API (Instagram 로그인)"** 을 추가합니다.
3. 권한 `instagram_business_basic` 와 `instagram_business_content_publish` 를 추가합니다.
4. 대시보드의 *액세스 토큰 생성* 에서 내 계정을 연결하면 **토큰**과 **Instagram 사용자 ID** 가 나옵니다.
   이것이 `IG_ACCESS_TOKEN` 과 `IG_USER_ID` 입니다.

### 5. 스레드 API
1. 같은 Meta 앱에 사용 사례 **"Threads API 액세스"** 를 추가합니다.
2. 권한 `threads_basic` 와 `threads_content_publish` 를 추가합니다.
3. *역할 → Threads 테스터* 에 내 스레드 계정을 추가하고, 스레드 앱의 설정 → 계정 → 웹사이트 권한에서 초대를 수락합니다.
4. 대시보드에서 토큰을 생성합니다. 이것이 `THREADS_ACCESS_TOKEN` 입니다.

> 내 계정에만 게시하는 용도라면 앱 검수(App Review) 없이 개발 모드로 쓸 수 있습니다.

### 6. GitHub Secrets 등록
저장소 **Settings → Secrets and variables → Actions → New repository secret** 에
`.env.example` 에 있는 이름 그대로 값을 넣습니다. (`OPENAI_API_KEY`, `REDDIT_*` 는 선택)

### 7. 첫 실행
**Actions 탭 → 카드뉴스 만들기 → Run workflow** 를 누르면 몇 분 안에 텔레그램으로 미리보기가 옵니다.
미리보기가 온 뒤 40분 안에 ✅ 를 누르면 바로 게시됩니다. 그 뒤에 누르면 게시까지 몇 시간 걸릴 수 있습니다.

---

## 자주 바꾸는 설정 (`config.yaml`)

| 항목 | 설명 |
|---|---|
| `brand` | 카드에 들어가는 계정 이름, 핸들, 포인트 색 |
| `approval` | `false` 로 바꾸면 완전 자동 게시 (민감 뉴스는 계속 승인 요청) |
| `feeds` | 수집할 외신 RSS 목록 |
| `llm` | `claude-code`(구독, 기본) 또는 `api`(API 키, 과금) |
| `cli_model` | 구독 방식에서 쓸 모델 (`sonnet`, `opus` 등). 비우면 기본 모델 |
| `threads.include_link` | 스레드 글에 기사 링크 넣기. 기본은 꺼짐 (출처 매체 이름은 항상 표기) |
| `threads.with_image` | `false` 로 바꾸면 스레드에 카드 없이 글만 게시 |
| 카드 생성 시간 | `.github/workflows/draft.yml` 의 `cron` (UTC 기준, 한국시간에서 9시간 빼기). GitHub 예약 실행은 30분~몇 시간 늦게 시작될 수 있어 정확한 시각은 보장되지 않음 |
| `approval_wait_minutes` | 미리보기를 보낸 뒤 버튼을 기다리는 시간(분). 늘리면 `draft.yml` 의 `timeout-minutes` 도 함께 늘리기 |

## 로컬에서 테스트

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m cardnews sample   # API 키 없이 카드 디자인만 확인 (output/sample.jpg)
python -m cardnews draft    # claude 에 로그인돼 있거나 .env 에 CLAUDE_CODE_OAUTH_TOKEN 이 있으면 실제 뉴스로 카드 생성
```

## 운영 시 알아둘 것

- **토큰 만료**: 인스타와 스레드 장기 토큰은 60일마다 만료됩니다. 50일쯤에
  `python -m cardnews refresh-tokens` 를 실행해 나온 새 토큰을 Secrets 에 다시 넣으세요.
  게시에 실패하면 텔레그램으로 알림이 옵니다.
- **비용**: 기본 설정(구독 토큰 + 무료 사진)이면 추가 비용이 0원입니다.
  카드 1장에 Claude 를 3번(글자 수 등 점검에 걸려 다시 쓰면 4번) 부르는데, 이것이 Pro 구독 사용량(5시간 단위, 주간 한도)에서 차감됩니다.
  하루 2장 정도는 여유가 있지만, 같은 시간대에 Claude 를 많이 쓰고 있었다면 한도에 걸려 실패할 수 있습니다.
  그럴 땐 텔레그램으로 실패 알림이 오고 다음 예약 시간에 다시 시도합니다.
  AI 이미지(`OPENAI_API_KEY`)는 넣었을 때만, 생성될 때만 비용이 듭니다.
- **구독 토큰 만료**: `claude setup-token` 토큰은 1년 동안 유효합니다. 만료되면 다시 만들어 Secrets 에 넣으세요.
- **자동 점검**: 글자 수나 낚시 표현에 걸리면 1번 다시 씁니다. 텔레그램 미리보기 맨 위의 ⚠️ 는 그래도 남은 문제와
  원문에서 못 찾은 숫자입니다. 계산한 값("23년 만에")도 표시되므로 게시를 막지는 않으니 눈으로 확인하세요.
- **GitHub Actions**: 공개 저장소는 무료입니다. 예약 실행은 30분~몇 시간 늦게 시작되거나 건너뛸 수 있습니다.
- 생성된 카드는 `output/` 에, 게시 이력은 `data/state.json` 에 쌓입니다.
