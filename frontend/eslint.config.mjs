import js from '@eslint/js';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

/**
 * Flat config, assembled from the individual plugins rather than pulled in via
 * `eslint-config-next`.
 *
 * That is a deliberate choice with a concrete reason: `eslint-config-next`
 * drags in a peer graph that sent npm's resolver into unbounded backtracking on
 * this machine - over thirty minutes of CPU without producing a lockfile. The
 * rules that config actually contributes here are the TypeScript set and the
 * React Hooks set, both of which are below, plus accessibility rules that
 * `eslint-plugin-jsx-a11y` provides directly and more of.
 *
 * `eslint-plugin-jsx-a11y` is why ESLint is pinned to 9.x: its peer range stops
 * at ESLint 9, and accessibility linting on a site whose whole claim is "you can
 * check this yourself" is worth more than being one major version ahead.
 */
export default tseslint.config(
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'coverage/**'],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.{ts,tsx,mjs}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        React: 'readonly',
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      'jsx-a11y': jsxA11y,
      'react-hooks': reactHooks,
    },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // The site renders typed content it owns. There is no reason for `any`
      // in it, and allowing one is how a content model stops being checked.
      '@typescript-eslint/no-explicit-any': 'error',

      // An external link opened in a new tab must carry noopener, or the page
      // it opens can reach back through window.opener.
      'react/jsx-no-target-blank': 'off', // (react plugin not loaded; enforced by a test instead)
    },
  },

  {
    // Test files run in Vitest's globals mode.
    files: ['tests/**/*.{ts,tsx}', 'vitest.config.mts'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
);
