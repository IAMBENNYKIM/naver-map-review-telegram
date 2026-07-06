# 네이버 리뷰 요약 — 웹 프론트엔드

네이버 지도 리뷰 요약 봇의 웹 진입점(설치형 PWA)입니다. 지인이 초대코드로
로그인해 `naver.me` URL 을 넣으면 리뷰 요약을 카드로 확인할 수 있습니다.

- **스택**: Next.js 15 (App Router) · TypeScript · Tailwind CSS v4 · React Hook Form + Zod · Lucide React
- **백엔드**: 별도 서버리스 API (이 저장소 루트의 Python/SAM 프로젝트). 프론트엔드는
  클라이언트 fetch 로만 호출하며 API 주소는 환경변수로 주입합니다.

## 필요 환경변수

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | O | 백엔드 API 베이스 URL (예: API Gateway 스테이지 URL). 하드코딩하지 않고 이 변수로만 주입합니다. |

`NEXT_PUBLIC_` 접두사가 붙은 값은 빌드 시 클라이언트 번들에 인라인됩니다.
값을 바꾸면 다시 빌드/배포해야 반영됩니다. 값이 없으면 앱은 크래시하지 않고
"API 서버 주소가 설정되지 않았어요" 안내로 처리합니다.

## 로컬 실행

```bash
cd web-frontend
cp .env.local.example .env.local   # 값을 실제 API 주소로 채우세요
npm install
npm run dev                        # http://localhost:3000
```

기타 명령:

```bash
npm run build   # 프로덕션 빌드 (타입/빌드 검사 포함)
npm run start   # 빌드 결과 실행
npm run lint    # ESLint
```

## 주요 화면

- `/` — 초대 게이트(토큰 없으면) 또는 분석 화면. 세션 토큰은 `localStorage`
  (`naverReviewSessionToken`)에 저장하고, 로그아웃 시 삭제합니다.
- `/admin` — 관리자 통계. 관리자 토큰은 메모리에만 두며 영구 저장하지 않습니다.
- `/share` — PWA 웹 공유 타겟 착지 경로. 공유된 텍스트에서 네이버 URL 을 추출해
  메인 입력창(`/?prefill=...`)을 채웁니다.

## PWA / 공유 타겟

- `src/app/manifest.ts` 가 `/manifest.webmanifest` 를 생성하며 설치용 아이콘과
  `share_target`(method GET)을 정의합니다.
- 네이버 앱에서 "공유 → 이 앱"으로 보내면 공유 데이터가 `/share` 로 전달됩니다.
- 지원 한계: `share_target` 은 주로 Android Chrome 등에서 동작하며, iOS 사파리 등
  일부 브라우저는 지원하지 않습니다(best-effort). POST 방식 공유 타겟은 서비스워커가
  필요해 여기서는 GET 만 사용합니다.
- 아이콘(`public/icon-192.png`, `icon-512.png`, `apple-touch-icon.png`)은 단색
  플레이스홀더입니다. 실제 브랜드 아이콘으로 교체하세요.

## Vercel 배포 메모

- 이 폴더(`web-frontend/`)는 모노레포 하위의 독립 Next.js 앱입니다. Vercel 프로젝트의
  **Root Directory 를 `web-frontend` 로 지정**하세요.
- 환경변수 `NEXT_PUBLIC_API_BASE_URL` 를 Vercel 프로젝트 설정에 등록합니다.
- 백엔드(API Gateway) 쪽에 이 프론트엔드 도메인에 대한 **CORS 허용**이 필요합니다.
- 실제 배포는 별도 작업(5-5)에서 사용자가 수행합니다.
