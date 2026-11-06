import fs from 'node:fs';
import { publishTistory } from './publishTistory.js';

/**
 * Python 파이프라인 브리지용 CLI.
 *
 * 사용법: node src/publishCli.js <payload.json>
 *
 * payload.json:
 * {
 *   "title": "...",
 *   "contentHtml": "<p>...</p>",
 *   "tags": ["..."],
 *   "tistoryCategory": "주식 정보",
 *   "visibility": "private",
 *   "blogName": "eneru",
 *   "imagePaths": ["C:/.../static/charts/xxx.png"],
 *   "debug": false,
 *   // 선택: 블로그별 발행 엔진 오버라이드 (Crystal / Quartz)
 *   "storageStatePath": ".state/crystal_storage_state.json",
 *   "kakaoId": "...",
 *   "kakaoPassword": "...",
 *   "artifactDir": "artifacts/tistory-errors/crystal",
 *   "headless": true
 * }
 *
 * 결과는 stdout 의 마지막 줄에 sentinel 로 출력한다:
 *   __PUBLISH_RESULT__{"ok":true,"publishedUrl":"..."}
 */
const SENTINEL = '__PUBLISH_RESULT__';

function emit(payload) {
  process.stdout.write(`\n${SENTINEL}${JSON.stringify(payload)}\n`);
}

function classify(message) {
  if (/auth\/login|login\.tistory|login_id|세션|storage state/i.test(message)) {
    return 'TISTORY_SESSION_EXPIRED';
  }
  if (/선택자|selector|메뉴 항목을 찾을 수 없음/i.test(message)) {
    return 'TISTORY_SELECTOR_MISSING';
  }
  if (/이미지 업로드/i.test(message)) {
    return 'TISTORY_IMAGE_UPLOAD_FAILED';
  }
  return 'TISTORY_PUBLISH_FAILED';
}

async function main() {
  const payloadPath = process.argv[2];
  if (!payloadPath) {
    emit({ ok: false, error: 'payload path is required', errorCode: 'TISTORY_BAD_PAYLOAD' });
    process.exitCode = 2;
    return;
  }

  let payload;
  try {
    const raw = fs.readFileSync(payloadPath, 'utf8').replace(/^\uFEFF/, '');
    payload = JSON.parse(raw);
  } catch (err) {
    emit({ ok: false, error: `payload read failed: ${err.message}`, errorCode: 'TISTORY_BAD_PAYLOAD' });
    process.exitCode = 2;
    return;
  }

  try {
    const result = await publishTistory(payload);
    emit({ ok: true, publishedUrl: result.publishedUrl });
  } catch (err) {
    const message = String(err?.message || err);
    emit({ ok: false, error: message, errorCode: err?.code || classify(message) });
    process.exitCode = 1;
  }
}

main();
