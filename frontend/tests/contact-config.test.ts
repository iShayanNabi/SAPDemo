/**
 * Configuration readiness, and the import boundary that keeps secrets off the
 * browser.
 *
 * The second half of this file is the one that matters most. `config.ts`,
 * `mailer.ts`, `rate-limit.ts` and `turnstile.ts` read the SMTP password, the
 * Turnstile secret and the rate-limit HMAC key. A single import of any of them
 * from a `'use client'` component compiles all of it into the JavaScript every
 * visitor downloads, and nothing about the page would look wrong. Next.js does
 * not error on this - it bundles it.
 *
 * Reading the import graph statically catches it before a build does.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_RATE_LIMIT_MAX,
  DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
  DEFAULT_SITEVERIFY_TIMEOUT_MS,
  isContactFormAvailable,
  isContactFormRequested,
  readContactConfig,
  siteverifyTimeoutMs,
  turnstileSiteKey,
} from '@/lib/contact/config';

const COMPLETE = {
  CONTACT_FORM_ENABLED: 'true',
  CONTACT_RECIPIENT_EMAIL: 'inbox@example.com',
  SMTP_HOST: 'smtp.example.com',
  SMTP_PORT: '587',
  SMTP_USER: 'sender@example.com',
  SMTP_APP_PASSWORD: 'not-a-real-password',
  TURNSTILE_SECRET_KEY: 'test-turnstile-secret',
  CONTACT_RATE_LIMIT_SECRET: 'test-rate-limit-secret',
  NEXT_PUBLIC_TURNSTILE_SITE_KEY: '1x00000000000000000000AA',
};

function configure(overrides: Record<string, string | undefined> = {}) {
  for (const [key, value] of Object.entries({ ...COMPLETE, ...overrides })) {
    vi.stubEnv(key, value ?? '');
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('isContactFormRequested', () => {
  it('defaults to false when unset', () => {
    vi.stubEnv('CONTACT_FORM_ENABLED', '');
    expect(isContactFormRequested()).toBe(false);
  });

  /**
   * Docker supplies a defined empty string rather than an absent variable, so
   * "unset" and "blank" have to mean the same thing. This is the same trap
   * `fromEnv` in `lib/site.ts` exists for.
   */
  it.each(['', '   ', 'false', 'FALSE', '0', 'no', 'off', 'Off'])(
    'treats %o as off',
    (value) => {
      vi.stubEnv('CONTACT_FORM_ENABLED', value);
      expect(isContactFormRequested()).toBe(false);
    },
  );

  it.each(['true', 'TRUE', '1', 'yes', 'on'])('treats %o as on', (value) => {
    vi.stubEnv('CONTACT_FORM_ENABLED', value);
    expect(isContactFormRequested()).toBe(true);
  });
});

describe('readContactConfig', () => {
  it('is ready when every variable is present', () => {
    configure();
    const result = readContactConfig();
    expect(result.ready).toBe(true);
    if (result.ready) {
      expect(result.config.recipient).toBe('inbox@example.com');
      expect(result.config.smtp.port).toBe(587);
      expect(result.config.rateLimit.maxPerWindow).toBe(DEFAULT_RATE_LIMIT_MAX);
    }
  });

  it.each([
    'CONTACT_RECIPIENT_EMAIL',
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_USER',
    'SMTP_APP_PASSWORD',
    'TURNSTILE_SECRET_KEY',
    'CONTACT_RATE_LIMIT_SECRET',
    'NEXT_PUBLIC_TURNSTILE_SITE_KEY',
  ])('is not ready when %s is missing, and names it', (variable) => {
    configure({ [variable]: undefined });
    const result = readContactConfig();
    expect(result.ready).toBe(false);
    if (!result.ready) {
      expect(result.missing).toContain(variable);
    }
  });

  it('reports every missing variable at once', () => {
    configure({ SMTP_HOST: undefined, TURNSTILE_SECRET_KEY: undefined });
    const result = readContactConfig();
    if (!result.ready) {
      expect(result.missing).toEqual(
        expect.arrayContaining(['SMTP_HOST', 'TURNSTILE_SECRET_KEY']),
      );
    }
  });

  describe('SMTP_SECURE', () => {
    it('defaults to implicit TLS on port 465', () => {
      configure({ SMTP_PORT: '465' });
      const result = readContactConfig();
      if (result.ready) expect(result.config.smtp.secure).toBe(true);
    });

    it('defaults to STARTTLS on 587', () => {
      configure({ SMTP_PORT: '587' });
      const result = readContactConfig();
      if (result.ready) expect(result.config.smtp.secure).toBe(false);
    });

    it('can be overridden explicitly', () => {
      configure({ SMTP_PORT: '2525', SMTP_SECURE: 'true' });
      const result = readContactConfig();
      if (result.ready) expect(result.config.smtp.secure).toBe(true);
    });
  });

  describe('SMTP_FROM', () => {
    it('falls back to the authenticated user', () => {
      configure({ SMTP_FROM: undefined });
      const result = readContactConfig();
      if (result.ready) expect(result.config.smtp.from).toBe('sender@example.com');
    });
  });

  describe('CONTACT_RATE_LIMIT_MAX', () => {
    it('uses the configured value', () => {
      configure({ CONTACT_RATE_LIMIT_MAX: '12' });
      const result = readContactConfig();
      if (result.ready) expect(result.config.rateLimit.maxPerWindow).toBe(12);
    });

    /**
     * A typo in an environment file must not open the endpoint. Every one of
     * these falls back to the default rather than to "no limit".
     */
    it.each(['', '   ', 'abc', '0', '-5', '3.5', 'Infinity', 'NaN'])(
      'falls back to the default for %o',
      (value) => {
        configure({ CONTACT_RATE_LIMIT_MAX: value });
        const result = readContactConfig();
        if (result.ready) expect(result.config.rateLimit.maxPerWindow).toBe(DEFAULT_RATE_LIMIT_MAX);
      },
    );
  });

  describe('CONTACT_RATE_LIMIT_WINDOW_SECONDS', () => {
    it('is converted to milliseconds', () => {
      configure({ CONTACT_RATE_LIMIT_WINDOW_SECONDS: '900' });
      const result = readContactConfig();
      if (result.ready) expect(result.config.rateLimit.windowMs).toBe(900_000);
    });

    it.each(['', '   ', 'abc', '0', '-1', '60.5'])(
      'falls back to the default for %o',
      (value) => {
        configure({ CONTACT_RATE_LIMIT_WINDOW_SECONDS: value });
        const result = readContactConfig();
        if (result.ready) {
          expect(result.config.rateLimit.windowMs).toBe(DEFAULT_RATE_LIMIT_WINDOW_SECONDS * 1000);
        }
      },
    );
  });

  describe('Turnstile pinning', () => {
    it('parses a comma-separated hostname list, lowercased', () => {
      configure({ TURNSTILE_EXPECTED_HOSTNAMES: 'SolveAIHub.com, www.solveaihub.com' });
      const result = readContactConfig();
      if (result.ready) {
        expect(result.config.turnstile.expectedHostnames).toEqual([
          'solveaihub.com',
          'www.solveaihub.com',
        ]);
      }
    });

    it('drops blank entries from a hand-edited list', () => {
      configure({ TURNSTILE_EXPECTED_HOSTNAMES: 'a.com,,b.com,' });
      const result = readContactConfig();
      if (result.ready) {
        expect(result.config.turnstile.expectedHostnames).toEqual(['a.com', 'b.com']);
      }
    });

    /**
     * Unset means "do not pin", which is the local-development case. It is not
     * required for readiness: `success` is still mandatory either way, so an
     * unpinned deployment is weaker but never unverified.
     */
    it('is empty and still ready when unconfigured', () => {
      configure({ TURNSTILE_EXPECTED_HOSTNAMES: undefined, TURNSTILE_EXPECTED_ACTION: undefined });
      const result = readContactConfig();
      expect(result.ready).toBe(true);
      if (result.ready) {
        expect(result.config.turnstile.expectedHostnames).toEqual([]);
        expect(result.config.turnstile.expectedAction).toBe('');
      }
    });
  });

  describe('SMTP_PORT', () => {
    it.each(['', 'abc', '0', '70000', '-1'])('is not ready for the invalid port %o', (value) => {
      configure({ SMTP_PORT: value });
      expect(readContactConfig().ready).toBe(false);
    });
  });
});

/**
 * The site key arrives by two routes, and this suite can only see one of them.
 *
 * `next build` replaces the literal `process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY`
 * with whatever the build argument held. Vitest does no such substitution, so
 * both reads in `turnstileSiteKey()` resolve to the same live `process.env`
 * here and no assertion can tell them apart. What is asserted instead is the
 * behaviour that matters at run time - the value is read on every call rather
 * than frozen - plus, structurally, that the second read really is written in
 * the form the compiler cannot match.
 */
describe('turnstileSiteKey', () => {
  it('reads the key the container was given', () => {
    configure({ NEXT_PUBLIC_TURNSTILE_SITE_KEY: '1x00000000000000000000AA' });
    expect(turnstileSiteKey()).toBe('1x00000000000000000000AA');
  });

  it.each(['', '   ', undefined])('treats %o as absent', (value) => {
    configure({ NEXT_PUBLIC_TURNSTILE_SITE_KEY: value });
    expect(turnstileSiteKey()).toBe('');
    expect(readContactConfig().ready).toBe(false);
  });

  /**
   * The deployment symptom this fixes: the container's environment has the
   * key, so a restart must be enough. Reading at module scope would freeze
   * whatever was set when the standalone server first imported this file.
   */
  it('is read on every call rather than at import time', () => {
    configure({ NEXT_PUBLIC_TURNSTILE_SITE_KEY: '' });
    expect(turnstileSiteKey()).toBe('');
    vi.stubEnv('NEXT_PUBLIC_TURNSTILE_SITE_KEY', '2x00000000000000000000BB');
    expect(turnstileSiteKey()).toBe('2x00000000000000000000BB');
  });

  it('keeps one compiled read and one runtime read', () => {
    /*
     * Only `next build` can distinguish these, so the guard is structural.
     *
     * The compiled read has to stay a complete literal expression - it is the
     * only form the compiler substitutes, and the browser bundle has no other
     * source for the key.
     *
     * The runtime read has to keep going through `globalThis`. Writing it as
     * `process.env[SITE_KEY_VARIABLE]`, or through a helper that returns
     * `process.env`, both compile to the build-time value: the constant and
     * the helper are folded first. That failure is silent - the source still
     * reads as a fallback, and the gate still refuses on a container that has
     * the variable - so the shape is asserted here and the emitted chunk was
     * read to establish it.
     */
    const source = readFileSync(join(ROOT, 'lib/contact/config.ts'), 'utf8');
    expect(source).toContain('process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY');
    expect(source).toMatch(/SITE_KEY_VARIABLE\s*=\s*'NEXT_PUBLIC_TURNSTILE_SITE_KEY'/);
    expect(source).toMatch(/runtimeEnv\(\)\[\s*SITE_KEY_VARIABLE\s*\]/);
    expect(source).toMatch(/globalThis\s+as\s+\{\s*process\?/);
  });
});

describe('siteverifyTimeoutMs', () => {
  it('defaults to five seconds when unset', () => {
    vi.stubEnv('CONTACT_SITEVERIFY_TIMEOUT_MS', '');
    expect(siteverifyTimeoutMs()).toBe(DEFAULT_SITEVERIFY_TIMEOUT_MS);
    expect(DEFAULT_SITEVERIFY_TIMEOUT_MS).toBe(5000);
  });

  it('uses the configured value', () => {
    vi.stubEnv('CONTACT_SITEVERIFY_TIMEOUT_MS', '2500');
    expect(siteverifyTimeoutMs()).toBe(2500);
  });

  /**
   * A malformed value must not become "wait for ever". `'3.5'` is the one
   * worth naming: `Number.parseInt` reports success on the `3` it understood,
   * which would silently run a three-millisecond timeout - every submission
   * refused, and nothing in the environment file to explain it.
   */
  it.each(['   ', 'abc', '0', '-1', '3.5', '5000ms', 'Infinity'])(
    'falls back to the default for %o',
    (value) => {
      vi.stubEnv('CONTACT_SITEVERIFY_TIMEOUT_MS', value);
      expect(siteverifyTimeoutMs()).toBe(DEFAULT_SITEVERIFY_TIMEOUT_MS);
    },
  );

  it('is not readable through a NEXT_PUBLIC_ name', () => {
    // It is not public, and compiling it in would mean a rebuild to change a
    // timeout. Nothing may start reading a `NEXT_PUBLIC_` spelling of it.
    const source = readFileSync(join(ROOT, 'lib/contact/config.ts'), 'utf8');
    expect(source).not.toContain('NEXT_PUBLIC_CONTACT_SITEVERIFY_TIMEOUT_MS');
  });
});

describe('isContactFormAvailable', () => {
  it('is true only when requested and fully configured', () => {
    configure();
    expect(isContactFormAvailable()).toBe(true);
  });

  it('is false when requested but incomplete', () => {
    configure({ TURNSTILE_SECRET_KEY: undefined });
    expect(isContactFormAvailable()).toBe(false);
  });

  it('is false when fully configured but not requested', () => {
    configure({ CONTACT_FORM_ENABLED: 'false' });
    expect(isContactFormAvailable()).toBe(false);
  });
});

/* ------------------------------------------------------------------------ */
/* The import boundary                                                       */
/* ------------------------------------------------------------------------ */

const ROOT = join(__dirname, '..');
const SERVER_ONLY_MODULES = ['contact/config', 'contact/mailer', 'contact/rate-limit', 'contact/turnstile'];

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (['node_modules', '.next', '.git'].includes(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      found.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

/** Every file carrying the `'use client'` directive. */
function clientComponents(): string[] {
  return sourceFiles(ROOT).filter((file) => {
    const head = readFileSync(file, 'utf8').slice(0, 200);
    return /^\s*['"]use client['"]/m.test(head);
  });
}

/**
 * Strip comments, then collect the module specifiers a file actually imports.
 *
 * Searching the raw text for a module name does not work, and failing that way
 * is worse than not testing at all: every file in this feature *documents* the
 * boundary in its header comment, so a substring search reports
 * `ContactForm.tsx` as importing `lib/contact/config` on the strength of the
 * sentence explaining why it must never do so. The assertion then fails on
 * prose, and the next person deletes it.
 *
 * Comments are removed first so a specifier inside one cannot be mistaken for
 * an import, and only `import`/`export ... from`, `require()` and dynamic
 * `import()` are read.
 */
function importedModules(file: string): string[] {
  const source = readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

  const specifiers: string[] = [];
  const patterns = [
    /(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*['"]([^'"]+)['"]/g,
    /(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g,
    /\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
    /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const specifier = match[1];
      if (specifier) specifiers.push(specifier);
    }
  }
  return specifiers;
}

describe('secrets cannot reach the browser bundle', () => {
  it('finds the client components it is meant to be checking', () => {
    // Guards the guard: a glob that matches nothing passes every assertion
    // below without checking anything.
    const files = clientComponents();
    expect(files.length).toBeGreaterThan(0);
    expect(files.some((f) => f.endsWith('ContactForm.tsx'))).toBe(true);
  });

  it('parses imports rather than searching text', () => {
    // The guard's own guard. `ContactForm.tsx` names every server-only module
    // in the comment explaining why it must not import them, so a substring
    // search reports it as an offender. If this ever fails, the assertions
    // below are matching prose again.
    const form = join(ROOT, 'components/ContactForm.tsx');
    expect(readFileSync(form, 'utf8')).toContain('lib/contact/config');
    expect(importedModules(form)).not.toContain('@/lib/contact/config');
  });

  it.each(SERVER_ONLY_MODULES)('no client component imports lib/%s', (module) => {
    const offenders = clientComponents().filter((file) =>
      importedModules(file).some((specifier) => specifier.includes(module)),
    );
    expect(offenders.map((f) => f.replace(ROOT, ''))).toEqual([]);
  });

  /**
   * `validation.ts` is the deliberate exception: it is pure, holds no secret,
   * and is shared so the browser and the endpoint cannot drift. If it ever
   * grows an import of one of the modules above, it stops being safe to share
   * - and this catches that rather than waiting for a bundle to be inspected.
   */
  it('the shared validation module pulls in nothing server-only', () => {
    const imports = importedModules(join(ROOT, 'lib/contact/validation.ts'));

    // It imports nothing at all today, which is the strongest version of this.
    expect(imports).toEqual([]);

    const source = readFileSync(join(ROOT, 'lib/contact/validation.ts'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/.*$/gm, '$1');
    // And it reads no configuration, so there is nothing for it to leak.
    expect(source).not.toContain('process.env');
  });

  /**
   * A secret must never be prefixed `NEXT_PUBLIC_`, which would compile it in
   * regardless of which file reads it.
   */
  it('no secret is read through a NEXT_PUBLIC_ variable', () => {
    const source = SERVER_ONLY_MODULES.map((m) =>
      readFileSync(join(ROOT, `lib/${m}.ts`), 'utf8'),
    ).join('\n');

    for (const secret of [
      'NEXT_PUBLIC_TURNSTILE_SECRET',
      'NEXT_PUBLIC_SMTP',
      'NEXT_PUBLIC_CONTACT_RATE_LIMIT_SECRET',
      'NEXT_PUBLIC_CONTACT_RECIPIENT',
    ]) {
      expect(source).not.toContain(secret);
    }
  });
});
