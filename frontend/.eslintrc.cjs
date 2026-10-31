module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  rules: {
    // useAsync(fn, deps)의 deps도 useEffect처럼 검사한다
    'react-hooks/exhaustive-deps': ['warn', { additionalHooks: '^useAsync$' }],
    // 스트림 읽기 루프(while (true) { ... break })는 의도한 것
    'no-constant-condition': ['error', { checkLoops: false }],
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
  },
}
