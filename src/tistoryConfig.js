import 'dotenv/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const BLOG_DEFAULTS = {
  crystal: { blogName: 'rumbell', blogUrl: 'https://rumbell.tistory.com' },
  quartz: { blogName: 'quar1z', blogUrl: 'https://quar1z.tistory.com' },
};

function env(name, fallback = '') {
  const value = process.env[name];
  if (value === undefined || value === null || value === '') return fallback;
  return value;
}

function blogSubdomain(url, fallback = 'eneru') {
  const match = String(url || '').match(/https?:\/\/([A-Za-z0-9_-]+)\.tistory\.com/);
  if (match) return match[1];
  return String(url || '').replace(/^https?:\/\//, '').replace(/\/.*$/, '') || fallback;
}

function resolvePath(value, fallbackRelative) {
  const target = value || fallbackRelative;
  return path.isAbsolute(target) ? target : path.resolve(projectRoot, target);
}

function asBool(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value).toLowerCase() !== 'false';
}

/**
 * Build a tistory runtime config.
 *
 * Every value falls back to the original Obsidian env vars, so the existing
 * stock pipeline keeps working unchanged. The editorial pipeline passes
 * per-blog overrides (blogName, storageStatePath, kakaoId, ...).
 */
export function resolveTistoryConfig(overrides = {}) {
  const blogUrl = overrides.blogUrl ?? env('TISTORY_BLOG_URL', '');
  const blogName =
    overrides.blogName ?? (env('TISTORY_BLOG_NAME', '') || blogSubdomain(blogUrl, 'eneru'));
  const storageState = resolvePath(
    overrides.storageStatePath ?? env('TISTORY_STORAGE_STATE_PATH', ''),
    '.state/tistory_storage_state.json'
  );
  const artifactDir = resolvePath(
    overrides.artifactDir ?? env('TISTORY_ARTIFACT_DIR', ''),
    'artifacts/tistory-errors'
  );

  return {
    blogName,
    visibility: String(overrides.visibility ?? env('TISTORY_VISIBILITY', 'private')).toLowerCase(),
    headless: asBool(overrides.headless ?? env('TISTORY_HEADLESS', 'true'), true),
    timeout: Number(overrides.timeout ?? env('TISTORY_TIMEOUT', '30000')),
    publishDelayMs: Number(overrides.publishDelayMs ?? env('TISTORY_PUBLISH_DELAY_MS', '2000')),
    allowMissingImages: asBool(
      overrides.allowMissingImages ?? env('TISTORY_ALLOW_MISSING_IMAGES', 'false'),
      false
    ),
    // 자동 재로그인용 (GitHub Secrets). 없으면 silent 로그인만 시도한다.
    kakaoId: overrides.kakaoId ?? env('TISTORY_KAKAO_ID', ''),
    kakaoPassword: overrides.kakaoPassword ?? env('TISTORY_KAKAO_PASSWORD', ''),
    paths: {
      root: projectRoot,
      stateDir: path.dirname(storageState),
      storageState,
      artifactDir,
    },
  };
}

/**
 * Resolve a named blog's config from blog-specific env vars.
 *
 *   CRYSTAL_BLOG_NAME / CRYSTAL_STORAGE_STATE_PATH / CRYSTAL_KAKAO_ID / ...
 *   QUARTZ_BLOG_NAME  / QUARTZ_STORAGE_STATE_PATH  / QUARTZ_KAKAO_ID  / ...
 *
 * Blog-specific values win; the original TISTORY_* vars remain the fallback.
 */
export function resolveBlogConfig(blogKey) {
  const key = String(blogKey || '').toLowerCase();
  const defaults = BLOG_DEFAULTS[key];
  if (!defaults) return resolveTistoryConfig();

  const prefix = key.toUpperCase();
  return resolveTistoryConfig({
    blogName: env(`${prefix}_BLOG_NAME`, defaults.blogName),
    blogUrl: env(`${prefix}_BLOG_URL`, defaults.blogUrl),
    storageStatePath: env(
      `${prefix}_STORAGE_STATE_PATH`,
      env('TISTORY_STORAGE_STATE_PATH', `.state/${key}_storage_state.json`)
    ),
    artifactDir: env(`${prefix}_ARTIFACT_DIR`, env('TISTORY_ARTIFACT_DIR', `artifacts/tistory-errors/${key}`)),
    kakaoId: env(`${prefix}_KAKAO_ID`, env('TISTORY_KAKAO_ID', '')),
    kakaoPassword: env(`${prefix}_KAKAO_PASSWORD`, env('TISTORY_KAKAO_PASSWORD', '')),
    visibility: env(`${prefix}_VISIBILITY`, env('TISTORY_VISIBILITY', 'public')),
  });
}

/** Original Obsidian config (kept for backwards compatibility). */
export const tistoryConfig = resolveTistoryConfig();
