// =============================================================================
// 單元測試：passwordStrengthError / emailFormatError（規則鏈順序與通過條件）
// 執行方式：cd frontend && npm test
// =============================================================================

import assert from 'node:assert/strict';
import { emailFormatError, passwordStrengthError } from '../validation.ts';

// 假 t：回傳 key，方便斷言命中哪一條規則
const t = ((key: string) => key) as unknown as Parameters<typeof passwordStrengthError>[1];

assert.equal(passwordStrengthError('', t), 'auth:password.required');
assert.equal(passwordStrengthError('Ab1', t), 'auth:password.minLength');
assert.equal(passwordStrengthError('abcdefg1', t), 'auth:password.needUppercase');
assert.equal(passwordStrengthError('ABCDEFG1', t), 'auth:password.needLowercase');
assert.equal(passwordStrengthError('Abcdefgh', t), 'auth:password.needDigit');
assert.equal(passwordStrengthError('Abcdefg1', t), null);
// 規則順序：長度先於字元類別
assert.equal(passwordStrengthError('ab1', t), 'auth:password.minLength');

assert.equal(emailFormatError('', t), 'auth:email.required');
assert.equal(emailFormatError('no-at-sign', t), 'auth:email.invalid');
assert.equal(emailFormatError('a@b', t), 'auth:email.invalid');
assert.equal(emailFormatError('a b@c.d', t), 'auth:email.invalid');
assert.equal(emailFormatError('doctor@hospital.tw', t), null);

console.log('validation.test.mts: all assertions passed');
