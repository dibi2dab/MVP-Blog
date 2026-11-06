#!/usr/bin/env node
import { resolveBlogConfig, resolveTistoryConfig } from './tistoryConfig.js';
import { refreshSession } from './tistoryAuth.js';

/**
 * 발행 전에 저장된 로그인 세션이 유효한지 검사하고, 가능하면 자동 복구한다.
 *
 *   npm run session:check
 *   npm run session:check -- --blog crystal
 *   npm run session:check -- --blog quartz
 *
 * GitHub Actions 에서 파이프라인을 돌리기 전에 이 스크립트를 먼저 실행하면
 * 세션 만료를 초기에 명확히 알 수 있다. `--blog` 를 주면 CRYSTAL_* / QUARTZ_*
 * 환경변수(없으면 TISTORY_*)로 블로그별 세션 파일과 자격증명을 해석한다.
 */
function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return '';
  return process.argv[index + 1] || '';
}

const blog = argValue('--blog').toLowerCase();
const config = blog ? resolveBlogConfig(blog) : resolveTistoryConfig();

console.log(`세션 확인 대상: ${config.blogName} (${config.paths.storageState})`);

refreshSession({ headless: true, config })
  .then((result) => {
    console.log(`세션 확인 완료 (${result.method})`);
  })
  .catch((err) => {
    console.error(`세션 확인 실패 [${err.code || 'ERROR'}]: ${err.message}`);
    process.exit(1);
  });
