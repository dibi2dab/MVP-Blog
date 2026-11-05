#!/usr/bin/env node
import { refreshSession } from './tistoryAuth.js';

/**
 * 발행 전에 저장된 로그인 세션이 유효한지 검사하고, 가능하면 자동 복구한다.
 *
 *   npm run session:check
 *
 * GitHub Actions 에서 파이프라인을 돌리기 전에 이 스크립트를 먼저 실행하면
 * 세션 만료를 초기에 명확히 알 수 있다.
 */
refreshSession({ headless: true })
  .then((result) => {
    console.log(`세션 확인 완료 (${result.method})`);
  })
  .catch((err) => {
    console.error(`세션 확인 실패 [${err.code || 'ERROR'}]: ${err.message}`);
    process.exit(1);
  });
